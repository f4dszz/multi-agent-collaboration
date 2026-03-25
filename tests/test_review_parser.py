from __future__ import annotations

import unittest

from backend.app.domain.models import Decision, FindingSeverity
from backend.app.services.review_parser import parse_review_output


class ReviewParserTests(unittest.TestCase):
    def test_parse_structured_review_output(self) -> None:
        text = """
Decision: revise
Risk-Tags: security, architecture
Blockers:
- B1 | Missing rollback path | The plan has no rollback strategy.
Concerns:
- C1 | Weak acceptance criteria | The acceptance section is too vague.
Suggestions:
- S1 | Split milestones | Break delivery into two smaller milestones.
Summary:
- Needs a stronger control path.
""".strip()

        record = parse_review_output(text)

        self.assertEqual(Decision.REVISE, record.decision)
        self.assertEqual({"security", "architecture"}, record.risk_tags)
        self.assertEqual(3, len(record.findings))
        self.assertEqual(FindingSeverity.BLOCKER, record.findings[0].severity)

    def test_missing_structure_defaults_to_revise_with_blocker(self) -> None:
        record = parse_review_output("This output ignored the requested format.")

        self.assertEqual(Decision.REVISE, record.decision)
        self.assertEqual(1, len(record.findings))
        self.assertEqual("B1", record.findings[0].key)

    def test_markdown_wrapped_fields_and_rules_are_ignored(self) -> None:
        text = """
---
Decision: **approve**
Risk-Tags: `security`, `architecture`
---
Blockers:
- none
Concerns:
- none
Suggestions:
- none
Summary:
- Ready for the next gate.
""".strip()

        record = parse_review_output(text)

        self.assertEqual(Decision.APPROVE, record.decision)
        self.assertEqual({"security", "architecture"}, record.risk_tags)
        self.assertEqual([], record.findings)


if __name__ == "__main__":
    unittest.main()
