import asyncio

from voice.session_lifecycle import VoiceSessionLifecycle, VoiceSessionState


def test_new_generation_invalidates_old_callbacks():
    lifecycle = VoiceSessionLifecycle()
    first = lifecycle.start()
    lifecycle.enable_microphone(first)
    second = lifecycle.start()

    assert second != first
    assert not lifecycle.is_current(first)
    assert lifecycle.is_current(second)
    assert not lifecycle.accepts_microphone(first)


def test_shutdown_stops_microphone_and_is_idempotent():
    lifecycle = VoiceSessionLifecycle()
    generation = lifecycle.start()
    lifecycle.enable_microphone(generation)

    assert lifecycle.request_shutdown(generation)
    assert not lifecycle.request_shutdown(generation)
    assert not lifecycle.accepts_microphone(generation)
    assert lifecycle.snapshot().state == VoiceSessionState.SHUTTING_DOWN


def test_playback_drain_releases_shutdown_waiter():
    async def scenario():
        lifecycle = VoiceSessionLifecycle()
        generation = lifecycle.start()
        lifecycle.request_shutdown(generation)

        waiter = asyncio.create_task(lifecycle.wait_playback_drained(generation, timeout=0.5))
        await asyncio.sleep(0)
        lifecycle.mark_playback_drained(generation)

        assert await waiter
        assert lifecycle.stop(generation)
        assert lifecycle.snapshot().state == VoiceSessionState.STOPPED

    asyncio.run(scenario())
