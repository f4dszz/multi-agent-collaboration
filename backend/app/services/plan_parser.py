from __future__ import annotations

import re


STEP_PATTERN = re.compile(r"^(\d+)\.\s+(.+)$")


def extract_implementation_steps(markdown: str) -> list[dict[str, object]]:
    lines = markdown.splitlines()
    in_section = False
    current_step: dict[str, object] | None = None
    steps: list[dict[str, object]] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        normalized = stripped.lower().strip("# ").strip()

        if stripped.startswith("#"):
            if in_section and normalized != "implementation steps":
                break
            in_section = normalized == "implementation steps"
            continue

        if not in_section:
            continue

        match = STEP_PATTERN.match(stripped)
        if match:
            if current_step is not None:
                steps.append(_finalize_step(current_step))
            current_step = {
                "step_index": int(match.group(1)),
                "title": match.group(2).strip(),
                "detail_lines": [],
            }
            continue

        if current_step is None:
            continue
        if stripped:
            current_step["detail_lines"].append(stripped)

    if current_step is not None:
        steps.append(_finalize_step(current_step))

    if steps:
        return steps

    fallback = markdown.strip()
    if not fallback:
        return []
    return [
        {
            "step_index": 1,
            "title": "Execute approved plan",
            "detail": fallback,
        }
    ]


def _finalize_step(step: dict[str, object]) -> dict[str, object]:
    detail_lines = [str(line) for line in step.get("detail_lines", [])]
    detail = "\n".join(detail_lines).strip() or str(step["title"])
    return {
        "step_index": int(step["step_index"]),
        "title": str(step["title"]),
        "detail": detail,
    }
