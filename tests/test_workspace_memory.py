from __future__ import annotations

import unittest

from computer.code_tools import CodeTools
from computer.workspace import Workspace
from memory.memory import Memory, MemoryLayer
from tests.helpers import TempDirTestCase


class WorkspaceTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.workspace = Workspace(self.tmp / "ws")

    def test_write_read_and_change_detection(self) -> None:
        first = self.workspace.write("pasta/a.txt", "um")
        self.assertTrue(first.created)
        self.assertTrue(first.changed)
        same = self.workspace.write("pasta/a.txt", "um")
        self.assertFalse(same.changed)
        self.assertEqual(self.workspace.read("pasta/a.txt").content, "um")
        self.assertEqual(self.workspace.list_files(), ["pasta/a.txt".replace("/", __import__("os").sep)])

    def test_paths_outside_workspace_are_blocked(self) -> None:
        for path in ("../fora.txt", "../../etc/passwd", str(self.tmp / "fora.txt")):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.workspace.write(path, "x")

    def test_delete(self) -> None:
        self.workspace.write("b.txt", "x")
        self.workspace.delete("b.txt")
        with self.assertRaises(FileNotFoundError):
            self.workspace.read("b.txt")


class CodeToolsTests(TempDirTestCase):
    def test_run_python_reports_real_exit_code(self) -> None:
        workspace = Workspace(self.tmp / "ws")
        tools = CodeTools(workspace)
        tools.write_file("ok.py", "print('oi')")
        tools.write_file("erro.py", "raise SystemExit(3)")

        ok = tools.run_python("ok.py")
        self.assertTrue(ok["success"])
        self.assertEqual(ok["stdout"].strip(), "oi")

        erro = tools.run_python("erro.py")
        self.assertFalse(erro["success"])
        self.assertEqual(erro["return_code"], 3)

    def test_run_python_rejects_non_python(self) -> None:
        workspace = Workspace(self.tmp / "ws")
        workspace.write("a.txt", "x")
        with self.assertRaises(ValueError):
            CodeTools(workspace).run_python("a.txt")


class MemoryTests(TempDirTestCase):
    def test_remember_recall_forget(self) -> None:
        memory = Memory(self.database)
        memory.remember(MemoryLayer.PERSONAL, "nome", {"apelido": "Du"})
        memory.remember(MemoryLayer.PERSONAL, "nome", {"apelido": "Du", "cidade": "SP"})
        self.assertEqual(memory.recall(MemoryLayer.PERSONAL, "nome"), {"apelido": "Du", "cidade": "SP"})
        self.assertTrue(memory.forget(MemoryLayer.PERSONAL, "nome"))
        self.assertIsNone(memory.recall(MemoryLayer.PERSONAL, "nome"))

    def test_plain_strings_round_trip(self) -> None:
        memory = Memory(self.database)
        memory.remember(MemoryLayer.KNOWLEDGE, "frase", "texto simples")
        self.assertEqual(memory.recall(MemoryLayer.KNOWLEDGE, "frase"), "texto simples")


if __name__ == "__main__":
    unittest.main()
