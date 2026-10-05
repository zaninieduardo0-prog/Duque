from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from brain.natural_language_patch import _natural_file_plan, _safe_filename
from brain.planner import Planner, StepKind


class NaturalFilePlanningTests(unittest.TestCase):
    def test_create_desktop_file_from_natural_language(self) -> None:
        plan = _natural_file_plan(
            Planner(),
            'crie um arquivo chamado teste.txt na área de trabalho contendo "123". Não faça nenhuma outra ação.',
            {"write_any_file"},
        )
        assert plan is not None
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].kind, StepKind.TOOL)
        self.assertEqual(plan.steps[0].tool, "write_any_file")
        self.assertEqual(plan.steps[0].arguments["content"], "123")
        self.assertEqual(Path(plan.steps[0].arguments["path"]).name, "teste.txt")

    def test_read_desktop_file_from_natural_language(self) -> None:
        plan = _natural_file_plan(Planner(), "leia o arquivo teste.txt na área de trabalho", {"read_any_file"})
        assert plan is not None
        self.assertEqual(plan.steps[0].tool, "read_any_file")

    def test_path_traversal_is_rejected(self) -> None:
        self.assertIsNone(_safe_filename("..\\segredo.txt"))
        self.assertIsNone(_safe_filename("../segredo.txt"))
        self.assertEqual(_safe_filename("teste.txt"), "teste.txt")


class StabilityResponseTests(unittest.TestCase):
    def test_short_confirmation_guard_is_loaded(self) -> None:
        import brain.stability_patch as stability

        self.assertTrue(stability._wants_short_confirmation("faça tudo e apenas me confirme quando terminar"))
        self.assertFalse(stability._wants_short_confirmation("faça tudo e me explique o resultado"))

    def test_sitecustomize_can_be_loaded_without_side_effect_error(self) -> None:
        with mock.patch.dict("sys.modules", {}, clear=False):
            # Importar novamente deve ser seguro mesmo em ambiente de testes.
            import sitecustomize  # noqa: F401


if __name__ == "__main__":
    unittest.main()
