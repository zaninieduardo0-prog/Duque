from __future__ import annotations

import subprocess
import unittest

import diagnostico
from tests.helpers import TempDirTestCase


class DiagnosticoTests(TempDirTestCase):
    def test_keys(self) -> None:
        checks = {check.name: check for check in diagnostico.check_keys({"OPENAI_API_KEY": "sk-abcdefghijklmnop"})}
        self.assertEqual(checks["OPENAI_API_KEY"].status, diagnostico.OK)
        self.assertNotIn("abcdefghijkl", checks["OPENAI_API_KEY"].detail)  # chave nunca aparece inteira
        self.assertEqual(checks["ANTHROPIC_API_KEY"].status, diagnostico.WARN)
        missing = {check.name: check for check in diagnostico.check_keys({})}
        self.assertEqual(missing["OPENAI_API_KEY"].status, diagnostico.FAIL)

    def test_git_outside_repository(self) -> None:
        checks = diagnostico.check_git(self.tmp)
        self.assertEqual(checks[0].status, diagnostico.WARN)

    def test_git_branch_and_dirty_state(self) -> None:
        repo = self.tmp / "repo"
        repo.mkdir()
        for args in (["init", "-b", "main"], ["config", "user.name", "t"], ["config", "user.email", "t@t"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        (repo / "a.txt").write_text("1", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "x"], cwd=repo, check=True, capture_output=True)
        (repo / "a.txt").write_text("2", encoding="utf-8")
        checks = {check.name: check for check in diagnostico.check_git(repo)}
        self.assertEqual(checks["git branch"].status, diagnostico.OK)
        self.assertEqual(checks["git alterações locais"].status, diagnostico.WARN)

    def test_python_and_port_checks_run(self) -> None:
        self.assertIn(diagnostico.check_python().status, {diagnostico.OK, diagnostico.WARN})
        self.assertEqual(diagnostico.check_port(5999).name, "porta 5000")


if __name__ == "__main__":
    unittest.main()
