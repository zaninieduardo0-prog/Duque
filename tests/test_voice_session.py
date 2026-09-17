from __future__ import annotations

from voice.session import PlaybackFence


def test_new_session_invalidates_previous_generation() -> None:
    fence = PlaybackFence()
    first = fence.new_session()
    assert fence.can_enqueue(first, "old") is True

    second = fence.new_session()
    assert second != first
    assert fence.stale(first) is True
    assert fence.can_enqueue(first, "late") is False
    assert fence.can_enqueue(second, "new") is True


def test_shutdown_rejects_new_input_audio_but_allows_farewell_playback() -> None:
    fence = PlaybackFence()
    generation = fence.new_session()
    assert fence.can_enqueue(generation, "current") is True

    fence.shutdown()
    assert fence.stale(generation) is True
    assert fence.can_enqueue(generation, "late") is False
    assert fence.can_enqueue(generation, "farewell", allow_shutdown=True) is True
    assert fence.drained() is False

    assert fence.can_consume(generation) is True
    assert fence.can_consume(generation) is True
    assert fence.drained() is True


def test_discard_audio_clears_pending_playback() -> None:
    fence = PlaybackFence()
    generation = fence.new_session()
    assert fence.can_enqueue(generation, "current") is True
    assert fence.can_enqueue(generation, "current") is True
    assert fence.drained() is False

    assert fence.discard_audio(generation) is True
    assert fence.drained() is True


def test_close_resets_session() -> None:
    fence = PlaybackFence()
    generation = fence.new_session()
    fence.can_enqueue(generation, "current")
    fence.close()

    assert fence.drained() is True
    assert fence.can_enqueue(generation, "late") is False
