"""
Quiz agent self-check robustness against bad model output. No model needed
(the blind solver is stubbed). Run from the project root:

    python -m unittest discover tests
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import core, quiz_agent  # noqa: E402

QUIZ = {
    "statements": ["Plants release oxygen during photosynthesis.",
                   "Photosynthesis happens mainly in the roots of plants.",
                   "Chlorophyll absorbs light energy for photosynthesis."],
    "false_index": 1,
    "explanation": "Photosynthesis happens mainly in the leaves, not the roots of plants.",
}


def fake_reply(content: str):
    return mock.Mock(message=mock.Mock(content=content))


class TestBlindSolve(unittest.TestCase):
    def solve(self, content: str):
        with mock.patch.object(core, "chat", return_value=fake_reply(content)):
            return quiz_agent._blind_solve(QUIZ["statements"])

    def test_out_of_range_answers_are_ignored(self):
        for content in ['{"false_index": 3}', '{"false_index": -5}', '{"false_index": -1}']:
            with self.subTest(content):
                self.assertIsNone(self.solve(content))

    def test_valid_answers(self):
        self.assertEqual(self.solve('{"false_index": 1}'), 1)
        self.assertEqual(self.solve('```json\n{"false_index": "2"}\n```'), 2)

    def test_garbage_is_ignored(self):
        for content in ["statement 1", '{"false_index": null}', '{"false_index": [1]}']:
            with self.subTest(content):
                self.assertIsNone(self.solve(content))

    def check(self, *contents):
        log = []
        with mock.patch.object(core, "chat", side_effect=[fake_reply(c) for c in contents]):
            return quiz_agent.check_quiz(dict(QUIZ), log), log[-1]

    def test_out_of_range_solver_rejects_instead_of_crashing(self):
        problems, log = self.check(*['{"false_index": 7}'] * 3)
        self.assertTrue(problems)
        self.assertIsNone(log["solver_picked"])

    def test_two_agreeing_solves_accept_without_a_third_call(self):
        problems, log = self.check('{"false_index": 1}', '{"false_index": 1}')
        self.assertEqual(problems, [])
        self.assertEqual(log["solver_votes"], [1, 1])

    def test_majority_ignores_unanswered_solve(self):
        problems, log = self.check('{"false_index": 1}', "no idea", '{"false_index": 1}')
        self.assertEqual((problems, log["solver_picked"]), ([], 1))

    def test_majority_for_wrong_statement_is_rejected(self):
        problems, _ = self.check('{"false_index": 2}', '{"false_index": 0}', '{"false_index": 2}')
        self.assertIn("statement 2", problems[0])

    def test_no_majority_is_rejected(self):
        problems, log = self.check('{"false_index": 0}', '{"false_index": 1}', '{"false_index": 2}')
        self.assertIn("could not agree", problems[0])
        self.assertIsNone(log["solver_picked"])


class TestQuizFallback(unittest.TestCase):
    def test_fallback_is_not_marked_verified(self):
        with mock.patch.object(core, "chat", side_effect=RuntimeError("ollama down")):
            quiz = quiz_agent.generate_quiz_agent("photosynthesis")
        self.assertEqual((quiz["source"], quiz["verified"]), ("fallback", False))
        self.assertIn("photosynthesis", " ".join(quiz["statements"]).lower())


if __name__ == "__main__":
    unittest.main()
