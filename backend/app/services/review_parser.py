from __future__ import annotations

import re

from backend.app.domain.models import Decision, Finding, FindingSeverity, ReviewRecord


SECTION_SEVERITY = {
    "blockers": FindingSeverity.BLOCKER,
    "concerns": FindingSeverity.CONCERN,
    "suggestions": FindingSeverity.SUGGESTION,
}


def parse_review_output(text: str) -> ReviewRecord:
    lines = [line.rstrip() for line in text.splitlines()]
    decision = _parse_decision(lines)
    risk_tags = _parse_risk_tags(lines)
    findings: list[Finding] = []
    current_section: str | None = None
    counters = {
        FindingSeverity.BLOCKER: 0,
        FindingSeverity.CONCERN: 0,
        FindingSeverity.SUGGESTION: 0,
    }

    for line in lines:
        stripped = line.strip()
        if _is_horizontal_rule(stripped):
            continue
        normalized = stripped.lower().rstrip(":")
        if stripped.endswith(":"):
            current_section = normalized if normalized in SECTION_SEVERITY else None
            if current_section:
                continue
        if not current_section:
            continue
        if not stripped.startswith("-"):
            continue
        severity = SECTION_SEVERITY[current_section]
        raw = stripped[1:].strip()
        if raw.lower() in {"none", "n/a", "na"} or _is_horizontal_rule(raw):
            continue
        counters[severity] += 1
        explicit_key, title, detail = _parse_finding_parts(raw, severity, counters[severity])
        key = explicit_key or _default_key(severity, counters[severity])
        findings.append(
            Finding(
                key=key,
                title=title,
                detail=detail,
                severity=severity,
            )
        )

    if decision is Decision.REVISE and not findings:
        findings.append(
            Finding(
                key="B1",
                title="Review output was not parseable",
                detail="Reviewer did not follow the expected structured output format.",
                severity=FindingSeverity.BLOCKER,
            )
        )

    return ReviewRecord(decision=decision, findings=findings, risk_tags=risk_tags)


def _parse_decision(lines: list[str]) -> Decision:
    for line in lines:
        prefix, separator, value = line.partition(":")
        if separator and prefix.strip().lower() == "decision":
            normalized = _strip_markdown_wrappers(value.strip()).lower()
            if normalized in {"approve", "revise", "reject"}:
                return Decision(normalized)
    return Decision.REVISE


def _parse_risk_tags(lines: list[str]) -> set[str]:
    pattern = re.compile(r"^Risk-Tags:\s*(.+)\s*$", re.IGNORECASE)
    for line in lines:
        match = pattern.match(line.strip())
        if not match:
            continue
        raw = match.group(1).strip()
        if raw.lower() in {"none", "n/a", "na"}:
            return set()
        return {
            _strip_markdown_wrappers(tag).lower()
            for tag in raw.split(",")
            if _strip_markdown_wrappers(tag)
        }
    return set()


def _default_key(severity: FindingSeverity, index: int) -> str:
    prefix = {
        FindingSeverity.BLOCKER: "B",
        FindingSeverity.CONCERN: "C",
        FindingSeverity.SUGGESTION: "S",
    }[severity]
    return f"{prefix}{index}"


def _parse_finding_parts(raw: str, severity: FindingSeverity, index: int) -> tuple[str, str, str]:
    parts = [_strip_markdown_wrappers(part.strip()) for part in raw.split("|", 2)]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2 and re.fullmatch(r"[BCS]\d+", parts[0], re.IGNORECASE):
        return parts[0], parts[1], parts[1]
    default_key = _default_key(severity, index)
    title = parts[0] if parts else raw
    return default_key, title, title


def _strip_markdown_wrappers(text: str) -> str:
    cleaned = text.strip()
    wrappers = ("**", "__", "`", "*", "_")
    changed = True
    while cleaned and changed:
        changed = False
        for wrapper in wrappers:
            if cleaned.startswith(wrapper) and cleaned.endswith(wrapper) and len(cleaned) > len(wrapper) * 2:
                cleaned = cleaned[len(wrapper) : -len(wrapper)].strip()
                changed = True
    return cleaned


def _is_horizontal_rule(text: str) -> bool:
    return bool(text) and set(text) == {"-"} and len(text) >= 3
