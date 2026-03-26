from __future__ import annotations

import unittest

from backend.app.services.plan_parser import extract_implementation_steps


class PlanParserTests(unittest.TestCase):
    def test_extracts_numbered_implementation_steps(self) -> None:
        markdown = """
## Objective
Ship the feature.

## Implementation Steps
1. Draft the API.
   - Define endpoints.
   - Add payload contracts.
2. Build the UI.
   - Render approvals.

## Risks
- Timeout.
""".strip()

        steps = extract_implementation_steps(markdown)

        self.assertEqual(2, len(steps))
        self.assertEqual("Draft the API.", steps[0]["title"])
        self.assertIn("Define endpoints.", steps[0]["detail"])
        self.assertEqual(2, steps[1]["step_index"])

    def test_falls_back_when_section_is_missing(self) -> None:
        steps = extract_implementation_steps("Plain text plan")

        self.assertEqual(1, len(steps))
        self.assertEqual("Execute approved plan", steps[0]["title"])


if __name__ == "__main__":
    unittest.main()
