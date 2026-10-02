from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

from brain.agent_loop import AgentLoop
from brain.model import NullModel
from brain.routines import split_commands
from computer.messaging import normalize_phone
from computer.workspace import Workspace
from memory.memory import Memory
from tests.helpers import TempDirTestCase


class HelpersTests(unittest.TestCase):
    def test_split_commands(self) -> None:
        self.assertEqual(split_commands("abre o vscode, abre o spotify e abre o github"), ["abre o vscode", "abre o spotify", "abre o github"])
        self.assertEqual(split_commands("modo foco por 50 minutos; pausa a música"), ["modo foco por 50 minutos", "pausa a música"])

    def test_phone(self) -> None:
        self.assertEqual(normalize_phone("(19) 99876-5432"), "5519998765432")
        self.assertEqual(normalize_phone("+55 19 99876 5432"), "5519998765432")
        self.assertIsNone(normalize_phone("123"))


class AgentSocialTests(TempDirTestCase):
    def make_agent(self, **env: str) -> AgentLoop:
        with mock.patch.dict(os.environ, {"DUQUE_FORGE": "0", **env}):
            agent = AgentLoop(tasks=self.tasks, workspace=Workspace(self.tmp / "ws"), model=NullModel(), memory=Memory(self.database))
        self.addCleanup(agent.scheduled_runner.stop)
        self.opened: list[str] = []
        agent.assistant_tools.open_target = self.opened.append
        agent.messaging.open_target = self.opened.append
        agent.focus_mode = lambda action="start", minutes=25: {"message": f"foco {minutes:g}"}  # type: ignore[method-assign]
        agent.executor.register("focus_mode", agent.focus_mode)
        return agent

    def test_create_and_run_routine(self) -> None:
        agent = self.make_agent()
        saved = agent.handle("crie a rotina estudo: modo foco por 50 minutos, abre o youtube")
        self.assertIn("Rotina 'estudo' salva com 2", saved.text)
        result = agent.handle("modo estudo")
        self.assertIn("Modo estudo ativado", result.text)
        self.assertIn("estudo", agent.handle("minhas rotinas").text)
        self.assertIn("Apaguei", agent.handle("apague a rotina estudo").text)
        self.assertIn("Não conheço", agent.handle("modo estudo").text)

    def test_default_routines_exist(self) -> None:
        agent = self.make_agent()
        self.assertTrue({"trabalho", "estudo", "jogo"} <= set(agent.routines.routines_list()["routines"]))

    def test_routine_with_unknown_command(self) -> None:
        agent = self.make_agent()
        result = agent.routines.routine_save("misto", "abre o spotify, faz um café")
        self.assertIn("Não entendi: faz um café", result["message"])
        self.assertFalse(agent.routines.routine_save("nada", "faz um café")["success"])

    def test_whatsapp_with_saved_contact(self) -> None:
        agent = self.make_agent()
        agent.handle("salve o contato João 19 99876-5432")
        result = agent.handle("manda uma mensagem pro João no whatsapp dizendo que vou atrasar 10 minutos")
        self.assertIn("pronta para João", result.text)
        self.assertEqual(self.opened[-1], "whatsapp://send?text=vou%20atrasar%2010%20minutos&phone=5519998765432")

    def test_whatsapp_unknown_contact_lets_user_choose(self) -> None:
        agent = self.make_agent()
        result = agent.handle("manda mensagem pra Maria: tô chegando")
        self.assertIn("Não tenho o número de 'Maria'", result.text)
        self.assertNotIn("phone=", self.opened[-1])

    def test_day_summary(self) -> None:
        agent = self.make_agent()
        agent.handle("quanto é 2+2?")
        agent.reminder_at("amanhã às 9h", "ligar pro banco")
        message = agent.handle("resumo do dia").text
        self.assertIn("Resumo do dia, Du", message)
        self.assertIn("Amanhã: 09:00 ligar pro banco", message)

    def test_daily_summary_is_scheduled_once(self) -> None:
        agent = self.make_agent(DUQUE_DAILY_SUMMARY="21:30")
        jobs = [job for job in agent.scheduler.list() if job.metadata.get("daily_summary")]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(datetime.fromtimestamp(jobs[0].run_at).strftime("%H:%M"), "21:30")
        agent._ensure_daily_summary()
        self.assertEqual(len([job for job in agent.scheduler.list() if job.metadata.get("daily_summary")]), 1)
        with mock.patch.dict(os.environ, {"DUQUE_DAILY_SUMMARY": "0"}):
            agent._ensure_daily_summary()
        self.assertEqual([job for job in agent.scheduler.list() if job.metadata.get("daily_summary")], [])

    def test_late_daily_summary_is_skipped_and_realigned(self) -> None:
        agent = self.make_agent(DUQUE_DAILY_SUMMARY="21:30")
        job = next(job for job in agent.scheduler.list() if job.metadata.get("daily_summary"))
        fired = (datetime.now() - timedelta(days=1)).replace(hour=21, minute=30) + timedelta(hours=10)  # 07:30 do dia seguinte
        job.last_run_at = fired.timestamp()
        before = agent.conversation.last_id()
        agent._on_reminder(job)
        self.assertEqual(agent.conversation.last_id(), before)
        self.assertEqual(datetime.fromtimestamp(job.run_at).strftime("%H:%M"), "21:30")
        self.assertGreater(job.run_at, fired.timestamp())

    def test_on_time_daily_summary_is_announced(self) -> None:
        agent = self.make_agent(DUQUE_DAILY_SUMMARY="21:30")
        job = next(job for job in agent.scheduler.list() if job.metadata.get("daily_summary"))
        job.last_run_at = datetime.now().replace(hour=21, minute=31).timestamp()
        agent._on_reminder(job)
        self.assertIn("Resumo do dia", agent.conversation.recent(1)[0].text)


if __name__ == "__main__":
    unittest.main()
