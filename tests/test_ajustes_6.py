"""Ajustes 6: TELEX — ativação local, "Repousar, Telex" e pausa de emergência retomável."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from core.emergency import EmergencyPause, describe, is_pause_command, is_resume_command
from core.voice_bridge import VoiceBridge
from voice.gate import ListenGate, addressed, is_sleep
from voice.local_wake import LocalWake, classify, decide, find_model, grammar


class TelexGateTests(unittest.TestCase):
    def test_telex_is_the_name(self) -> None:
        for phrase in ("Telex, abre o Spotify", "Tele X, que horas são", "teles, oi", "Télex"):
            with self.subTest(phrase=phrase):
                self.assertTrue(addressed(phrase))

    def test_old_names_still_work(self) -> None:
        self.assertTrue(addressed("Duque, abre o chrome"))

    def test_stop_with_new_name(self) -> None:
        gate = ListenGate()
        self.assertEqual(gate.decide("Telex, stop").action, "stop")

    def test_sleep(self) -> None:
        gate = ListenGate()
        self.assertEqual(gate.decide("Repousar, Telex").action, "sleep")
        self.assertEqual(gate.decide("repousar").action, "ignore")  # sem o nome: fundo
        self.assertTrue(is_sleep("Telex, repousar agora"))
        self.assertFalse(is_sleep("Telex, repousar o projeto amanhã"))


class LocalWakePhraseTests(unittest.TestCase):
    def test_wake_phrases(self) -> None:
        for phrase, greeting in (
            ("bom dia telex", "Bom dia, TELEX."),
            ("Boa tarde, Télex!", "Boa tarde, TELEX."),
            ("boa noite teles", "Boa noite, TELEX."),
        ):
            with self.subTest(phrase=phrase):
                heard = classify(phrase)
                assert heard is not None
                self.assertEqual(heard.kind, "wake")
                self.assertEqual(heard.greeting, greeting)

    def test_other_phrases_do_not_wake(self) -> None:
        for phrase in ("bom dia", "oi telex", "bom dia telex tudo bem", "", "telex"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(classify(phrase))

    def test_sleep_and_resume(self) -> None:
        sleep, resume = classify("repousar telex"), classify("retomar telex")
        assert sleep is not None and resume is not None
        self.assertEqual((sleep.kind, resume.kind), ("sleep", "resume"))

    def test_decide(self) -> None:
        wake, resume = classify("bom dia telex"), classify("retomar telex")
        self.assertEqual(decide(wake, False, False), ("wake", "Bom dia, TELEX."))
        self.assertEqual(decide(None, True, False), ("wake", None))  # Hey Jarvis
        self.assertEqual(decide(None, False, False), ("none", None))
        # Em pausa de emergência nada acorda; só "Retomar, TELEX" funciona.
        self.assertEqual(decide(wake, True, True), ("none", None))
        self.assertEqual(decide(resume, False, True), ("resume", None))
        self.assertEqual(decide(resume, False, False), ("none", None))

    def test_grammar_only_known_spellings(self) -> None:
        phrases = grammar(lambda word: word == "telex")
        self.assertIn("bom dia telex", phrases)
        self.assertIn("repousar telex", phrases)
        self.assertNotIn("bom dia teles", phrases)
        self.assertEqual(phrases[-1], "[unk]")

    def test_find_model_accepts_inner_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_model(tmp))
            (Path(tmp) / "vosk-model-small-pt-0.3" / "am").mkdir(parents=True)
            self.assertEqual(find_model(tmp), Path(tmp) / "vosk-model-small-pt-0.3")


class FakeModel:
    def find_word(self, word: str) -> int:
        return 7 if word in {"telex", "teles"} else -1


class FakeRecognizer:
    """Simula o Vosk: devolve os textos programados, um por frame."""

    script: list[tuple[str, str]] = []

    def __init__(self, _model: Any, rate: float, grammar_json: str) -> None:
        self.rate = rate
        self.grammar = json.loads(grammar_json)
        self.resets = 0

    def AcceptWaveform(self, _pcm: bytes) -> bool:
        kind, _ = self.script[0]
        return kind == "final"

    def Result(self) -> str:
        return json.dumps({"text": self.script.pop(0)[1]})

    def PartialResult(self) -> str:
        return json.dumps({"partial": self.script.pop(0)[1]})

    def Reset(self) -> None:
        self.resets += 1


class LocalWakeListenerTests(unittest.TestCase):
    def test_partial_triggers_without_waiting_for_silence(self) -> None:
        FakeRecognizer.script = [("partial", "bom"), ("partial", "bom dia"), ("partial", "bom dia telex")]
        listener = LocalWake(FakeModel(), FakeRecognizer)
        self.assertEqual(listener.names, ["teles", "telex"])
        self.assertIsNone(listener.feed(b"\0" * 2560))
        self.assertIsNone(listener.feed(b"\0" * 2560))
        heard = listener.feed(b"\0" * 2560)
        assert heard is not None
        self.assertEqual(heard.kind, "wake")
        self.assertEqual(listener._recognizer.resets, 1)

    def test_unknown_speech_is_ignored(self) -> None:
        FakeRecognizer.script = [("final", "[unk] [unk]"), ("final", "")]
        listener = LocalWake(FakeModel(), FakeRecognizer)
        self.assertIsNone(listener.feed(b""))
        self.assertIsNone(listener.feed(b""))

    def test_model_without_the_name_is_rejected(self) -> None:
        class Empty:
            def find_word(self, _word: str) -> int:
                return -1

        with self.assertRaises(RuntimeError):
            LocalWake(Empty(), FakeRecognizer)


class EmergencyPauseTests(unittest.TestCase):
    def test_checkpoint_waits_and_continues_from_same_place(self) -> None:
        pause = EmergencyPause(None)
        self.assertFalse(pause.checkpoint("x"))  # sem pausa: segue direto
        pause.pause("teste")
        done = threading.Event()
        log: list[str] = []

        def job() -> None:
            log.append("etapa 1")
            pause.checkpoint("tarefa:1", {"trabalho": "abrir apps", "etapa": "open_app"})
            log.append("etapa 2")
            done.set()

        worker = threading.Thread(target=job, daemon=True)
        worker.start()
        time.sleep(0.2)
        self.assertEqual(log, ["etapa 1"])  # parado no ponto seguro
        status = pause.status()
        self.assertTrue(status["pausado"])
        self.assertEqual(status["parado_em"][0]["etapa"], "open_app")
        was = pause.resume()
        self.assertEqual(was["parado_em"][0]["trabalho"], "abrir apps")
        self.assertTrue(done.wait(2))
        self.assertEqual(log, ["etapa 1", "etapa 2"])
        self.assertEqual(pause.status()["parado_em"], [])

    def test_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pausa.json"
            first = EmergencyPause(path)
            first.pause("botão")
            # Simula o processo morrendo com o trabalho parado.
            first._checkpoints["forja"] = {"trabalho": "Forja: notion", "etapa": "aguardando CI"}
            first._save()

            second = EmergencyPause(path)
            self.assertTrue(second.paused)
            interrupted = second.status()["interrompido"]
            self.assertEqual(interrupted[0]["etapa"], "aguardando CI")
            self.assertIn("reinício", describe(second.status()))
            second.resume()
            self.assertFalse(EmergencyPause(path).paused)

    def test_listeners(self) -> None:
        pause = EmergencyPause(None)
        seen: list[bool] = []
        pause.on_change(lambda paused, _status: seen.append(paused))
        pause.pause()
        pause.resume()
        self.assertEqual(seen, [True, False])

    def test_phrases(self) -> None:
        for phrase in ("Telex, pausa tudo", "pausa de emergência", "para tudo"):
            self.assertTrue(is_pause_command(phrase), phrase)
        for phrase in ("qual o número de emergência?", "pausa a música"):
            self.assertFalse(is_pause_command(phrase), phrase)
        for phrase in ("retomar", "Retomar, Telex", "pode continuar", "continua de onde parou"):
            self.assertTrue(is_resume_command(phrase), phrase)
        self.assertFalse(is_resume_command("retomar o projeto do site"))

    def test_describe(self) -> None:
        self.assertEqual(describe({}), "Nada estava em andamento.")
        text = describe({"parado_em": [{"trabalho": "Forja: notion", "etapa": "rodando testes"}]})
        self.assertIn("Forja: notion, em rodando testes", text)


class ExecutorPauseTests(unittest.TestCase):
    def test_step_waits_during_pause(self) -> None:
        from core.executor import Executor
        from core.tasks import TaskManager
        from memory.database import MemoryDatabase

        with tempfile.TemporaryDirectory() as tmp:
            pause = EmergencyPause(None)
            executor = Executor(TaskManager(MemoryDatabase(Path(tmp) / "m.db")), pause=pause)
            ran: list[int] = []
            executor.register("conta", lambda: ran.append(1) or {"success": True})
            task = executor.tasks.create("contar")
            pause.pause()
            result: list[Any] = []
            worker = threading.Thread(target=lambda: result.append(executor.execute_step(task, "conta")), daemon=True)
            worker.start()
            time.sleep(0.2)
            self.assertEqual(ran, [])
            self.assertEqual(pause.status()["parado_em"][0]["etapa"], "conta")
            pause.resume()
            worker.join(2)
            self.assertEqual(ran, [1])
            self.assertTrue(result[0].success)


class ForgePauseTests(unittest.TestCase):
    def test_forge_stops_between_stages(self) -> None:
        from forge.service import ForgeService

        class FakeForge:
            progress: Any = None

        service = ForgeService(FakeForge())  # type: ignore[arg-type]
        service.pause = EmergencyPause(None)
        service._current = {"id": "1", "goal": "adicionar notion", "step": "iniciando"}
        service.pause.pause()
        worker = threading.Thread(target=service._on_progress, args=(None, "aguardando CI no GitHub"), daemon=True)
        worker.start()
        time.sleep(0.2)
        self.assertTrue(worker.is_alive())
        where = service.pause.status()["parado_em"][0]
        self.assertEqual(where["etapa"], "aguardando CI no GitHub")
        self.assertIn("adicionar notion", where["trabalho"])
        service.pause.resume()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(service.status()["current"]["steps"], 1)


class BridgeEndVoiceTests(unittest.TestCase):
    def test_end_voice(self) -> None:
        bridge = VoiceBridge()
        self.assertFalse(bridge.end_voice())
        reasons: list[str] = []
        bridge.attach_session(lambda _t: True, None, reasons.append)
        self.assertTrue(bridge.end_voice("repousar"))
        self.assertEqual(reasons, ["repousar"])
        bridge.detach_session()
        self.assertFalse(bridge.end_voice())


@unittest.skipUnless(importlib.util.find_spec("openai") is not None, "servidor exige o pacote openai")
class EmergencyEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.test_conversation import ServerConversationTests

        cls.base = ServerConversationTests
        ServerConversationTests.setUpClass()
        cls.servidor = ServerConversationTests.servidor

    @classmethod
    def tearDownClass(cls) -> None:
        cls.base.tearDownClass()

    def setUp(self) -> None:
        self.client = self.servidor.app.test_client()
        self.servidor.agent.pause = EmergencyPause(None)
        self.addCleanup(self.servidor.bridge.detach_session)

    def test_pause_blocks_commands_until_resume(self) -> None:
        ended: list[str] = []
        self.servidor.bridge.attach_session(lambda _t: True, None, ended.append)
        data = self.client.post("/api/emergencia", json={"acao": "pausar"}).get_json()
        self.assertTrue(data["pausado"])
        self.assertEqual(ended, ["pausa de emergência"])  # a voz fecha na hora
        self.servidor.bridge.detach_session()

        blocked = self.client.post("/api/comando", json={"text": "quanto é 2+3?"}).get_json()
        self.assertTrue(blocked["pausado"])
        self.assertIn("pausa de emergência", blocked["text"])

        resumed = self.client.post("/api/comando", json={"text": "retomar"}).get_json()
        self.assertFalse(resumed["pausado"])
        self.assertEqual(self.client.post("/api/comando", json={"text": "quanto é 2+3?"}).get_json()["text"], "2+3 = 5")

    def test_typed_pause_and_toggle(self) -> None:
        self.assertTrue(self.client.post("/api/comando", json={"text": "Telex, pausa tudo"}).get_json()["pausado"])
        self.assertTrue(self.client.get("/api/emergencia").get_json()["pausado"])
        self.assertFalse(self.client.post("/api/emergencia", json={"acao": "alternar"}).get_json()["pausado"])
        self.assertEqual(self.client.post("/api/emergencia", json={"acao": "explodir"}).status_code, 400)

    def test_typed_sleep_closes_voice(self) -> None:
        ended: list[str] = []
        self.servidor.bridge.attach_session(lambda _t: True, None, ended.append)
        data = self.client.post("/api/comando", json={"text": "Repousar, Telex"}).get_json()
        self.assertEqual(data["via"], "repouso")
        self.assertEqual(ended, ["repousar"])

    def test_tasks_panel(self) -> None:
        data = self.client.get("/api/tarefas").get_json()
        self.assertIn("pausa", data)
        self.assertIn("forja", data)
        self.assertIsInstance(data["tarefas"], list)


class HudTelexTests(unittest.TestCase):
    def test_hud_has_logo_pause_and_tasks(self) -> None:
        html = (Path(__file__).resolve().parent.parent / "interface" / "index.html").read_text(encoding="utf-8")
        for needle in ('id="logo"', ">TELEX<", 'id="panicBtn"', 'id="pauseBox"', "/api/emergencia", "/api/tarefas", "F9"):
            self.assertIn(needle, html)
        self.assertNotIn('<div class="brand">DUQUE</div>', html)


if __name__ == "__main__":
    unittest.main()
