from __future__ import annotations

import unittest

from brain.natural_files import _safe_filename, clean_control_tail, natural_file_plan
from brain.planner import Planner, StepKind


class NaturalFilePlanningTests(unittest.TestCase):
    def test_create_desktop_file_from_natural_language(self) -> None:
        plan = natural_file_plan(
            'crie um arquivo chamado teste.txt na área de trabalho contendo "123". Não faça nenhuma outra ação.',
            {"save_text_file"},
        )
        assert plan is not None
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.kind, StepKind.TOOL)
        self.assertEqual(step.tool, "save_text_file")
        self.assertEqual(step.arguments, {"name": "teste.txt", "content": "123", "folder": "área de trabalho", "overwrite": True})

    def test_glued_assistant_prefix_and_documents(self) -> None:
        plan = natural_file_plan("DuDu crie um arquivo notas.txt em documentos contendo comprar pão", {"save_text_file"})
        assert plan is not None
        self.assertEqual(plan.steps[0].arguments["folder"], "documentos")
        self.assertEqual(plan.steps[0].arguments["content"], "comprar pão")

    def test_read_desktop_file_from_natural_language(self) -> None:
        plan = natural_file_plan("leia o arquivo teste.txt na área de trabalho", {"read_text_file"})
        assert plan is not None
        self.assertEqual(plan.steps[0].tool, "read_text_file")
        self.assertEqual(plan.steps[0].arguments, {"name_or_path": "teste.txt", "folder": "área de trabalho"})

    def test_planner_uses_it_for_file_operations(self) -> None:
        plan = Planner().build("crie um arquivo a.txt no desktop contendo oi", "file_operation", {"save_text_file"})
        self.assertEqual(plan.steps[0].tool, "save_text_file")

    def test_path_traversal_is_rejected(self) -> None:
        self.assertIsNone(_safe_filename("..\\segredo.txt"))
        self.assertIsNone(_safe_filename("../segredo.txt"))
        self.assertEqual(_safe_filename("teste.txt"), "teste.txt")
        self.assertEqual(clean_control_tail('"oi". Pare por aí.'), "oi")
        self.assertEqual(clean_control_tail("oi e apenas me confirme"), "oi")


if __name__ == "__main__":
    unittest.main()
