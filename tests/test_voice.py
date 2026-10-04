from __future__ import annotations

import unittest
from types import SimpleNamespace

from voice.session import PlaybackFence, error_details, is_benign_error, is_farewell, is_fatal_error


class PlaybackFenceTests(unittest.TestCase):
    def test_old_generation_is_rejected(self) -> None:
        fence = PlaybackFence()
        first = fence.new_session()
        self.assertTrue(fence.accepts(first))
        second = fence.new_session()
        self.assertFalse(fence.accepts(first))
        self.assertTrue(fence.accepts(second))
        fence.close()
        self.assertFalse(fence.accepts(second))


class RealtimeErrorTests(unittest.TestCase):
    def test_cancel_without_response_is_benign(self) -> None:
        error = SimpleNamespace(
            type="invalid_request_error",
            code="response_cancel_not_active",
            message="Cancellation failed: no active response found",
        )
        self.assertTrue(is_benign_error(error))
        self.assertFalse(is_fatal_error(error))

    def test_nested_dict_error(self) -> None:
        error = {"type": "error", "error": {"type": "invalid_request_error", "code": "conversation_already_has_active_response", "message": "x"}}
        self.assertEqual(error_details(error)[1], "conversation_already_has_active_response")
        self.assertTrue(is_benign_error(error))

    def test_request_errors_do_not_end_session(self) -> None:
        self.assertFalse(is_fatal_error({"type": "invalid_request_error", "code": "invalid_value", "message": "bad"}))
        self.assertFalse(is_fatal_error({"message": "Tool output send failed; cached output will be retried"}))

    def test_session_errors_end_session(self) -> None:
        self.assertTrue(is_fatal_error({"type": "invalid_request_error", "code": "session_expired", "message": "Your session hit the maximum duration"}))
        self.assertTrue(is_fatal_error({"type": "authentication_error", "code": "", "message": "bad key"}))


class FarewellTests(unittest.TestCase):
    def test_farewell(self) -> None:
        self.assertTrue(is_farewell("Ok, tchau,   Duque!"))
        self.assertFalse(is_farewell("tchau"))


if __name__ == "__main__":
    unittest.main()
