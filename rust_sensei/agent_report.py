from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

from rust_sensei.dto.assessment import AssessmentResultDTO
from rust_sensei.dto.lesson import LessonAssignmentDTO, LessonPlanDTO

_POSIX_LOCAL_PATH_RE = re.compile(r"/(?:Users|home)/[^\s`\"'<>),;]+")
_WINDOWS_LOCAL_PATH_RE = re.compile(
    r"[A-Za-z]:\\Users\\[^\s`\"'<>),;]+",
    flags=re.IGNORECASE,
)


def build_lesson_report(
    *,
    assignment: LessonAssignmentDTO,
    lesson_plan: LessonPlanDTO,
    assessment: AssessmentResultDTO,
    lesson_file_path: str | None = None,
    submitted_file_paths: Sequence[str] = (),
    commands_run_by_learner: Sequence[str] = (),
    verification_commands_run_by_agent: Sequence[str] = (),
    agent_guidance: str | None = None,
) -> str:
    _validate_report_inputs(assignment, lesson_plan, assessment)

    sections = [
        "# Rust Sensei Lesson Report",
        _assignment_section(assignment, lesson_plan),
        _artifact_section(lesson_file_path, submitted_file_paths),
        _command_section(commands_run_by_learner, verification_commands_run_by_agent),
        _assessment_summary_section(assessment),
        _assessment_json_section(assessment),
    ]
    if agent_guidance is not None and agent_guidance.strip():
        sections.append(_agent_guidance_section(agent_guidance))

    return "\n\n".join(sections) + "\n"


def write_lesson_report(
    report_file_path: Path,
    *,
    assignment: LessonAssignmentDTO,
    lesson_plan: LessonPlanDTO,
    assessment: AssessmentResultDTO,
    lesson_file_path: str | None = None,
    submitted_file_paths: Sequence[str] = (),
    commands_run_by_learner: Sequence[str] = (),
    verification_commands_run_by_agent: Sequence[str] = (),
    agent_guidance: str | None = None,
) -> Path:
    _atomic_write_text(
        report_file_path,
        build_lesson_report(
            assignment=assignment,
            lesson_plan=lesson_plan,
            assessment=assessment,
            lesson_file_path=lesson_file_path,
            submitted_file_paths=submitted_file_paths,
            commands_run_by_learner=commands_run_by_learner,
            verification_commands_run_by_agent=verification_commands_run_by_agent,
            agent_guidance=agent_guidance,
        ),
    )
    return report_file_path


def _validate_report_inputs(
    assignment: LessonAssignmentDTO,
    lesson_plan: LessonPlanDTO,
    assessment: AssessmentResultDTO,
) -> None:
    if assessment.assignment_id != assignment.assignment_id:
        raise ValueError(
            "assessment.assignment_id must match assignment.assignment_id"
        )
    if assignment.lesson_id != lesson_plan.lesson_id:
        raise ValueError("assignment.lesson_id must match lesson_plan.lesson_id")
    if assignment.concept_id != lesson_plan.concept_id:
        raise ValueError("assignment.concept_id must match lesson_plan.concept_id")


def _assignment_section(
    assignment: LessonAssignmentDTO,
    lesson_plan: LessonPlanDTO,
) -> str:
    return "\n".join(
        [
            "## Assignment",
            f"- Assignment id: `{assignment.assignment_id}`",
            f"- Lesson id: `{assignment.lesson_id}`",
            f"- Concept id: `{assignment.concept_id}`",
            f"- Difficulty: `{assignment.difficulty}`",
            f"- Variant id: `{assignment.variant_id}`",
            "",
            "### Prompt",
            _fenced_text(lesson_plan.prompt),
            "",
            "### Success Criteria",
            _markdown_list(lesson_plan.success_criteria),
        ]
    )


def _artifact_section(
    lesson_file_path: str | None,
    submitted_file_paths: Sequence[str],
) -> str:
    return "\n".join(
        [
            "## Submitted Artifacts",
            f"- Lesson source file: {_inline_markdown(lesson_file_path)}"
            if lesson_file_path
            else "- Lesson source file: not provided",
            "- Submitted file paths:",
            _markdown_list(submitted_file_paths),
        ]
    )


def _command_section(
    commands_run_by_learner: Sequence[str],
    verification_commands_run_by_agent: Sequence[str],
) -> str:
    return "\n".join(
        [
            "## Commands",
            "### Learner-Run Commands",
            _markdown_list(commands_run_by_learner),
            "",
            "### Agent Verification Commands",
            _markdown_list(verification_commands_run_by_agent),
        ]
    )


def _assessment_summary_section(assessment: AssessmentResultDTO) -> str:
    return "\n".join(
        [
            "## Rust Sensei Assessment Summary",
            f"- Assessment id: `{assessment.assessment_id}`",
            f"- Attempt id: `{assessment.attempt_id}`",
            f"- Status: `{assessment.assessment_status}`",
            f"- Confidence: `{assessment.confidence}`",
            f"- Next action: `{assessment.next_action.value}`",
            (
                f"- Branch id: `{_inline_markdown(assessment.branch_id)}`"
                if assessment.branch_id
                else "- Branch id: none"
            ),
            f"- Next action reason: {_inline_markdown(assessment.next_action_reason)}",
            f"- Feedback summary: {_inline_markdown(assessment.feedback_summary)}",
            "",
            "### Rubric Scores",
            _rubric_score_table(assessment),
            "",
            "### Confidence Explanation",
            _markdown_list(assessment.confidence_breakdown.explanation),
            "",
            "### Missing Evidence",
            _markdown_list(assessment.missing_evidence),
            "",
            "### Feedback Items",
            _feedback_items(assessment),
        ]
    )


def _assessment_json_section(assessment: AssessmentResultDTO) -> str:
    payload = json.dumps(
        assessment.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    )
    return "\n".join(
        [
            "## Canonical Rust Sensei Assessment JSON",
            "```json",
            payload,
            "```",
        ]
    )


def _agent_guidance_section(agent_guidance: str) -> str:
    return "\n".join(
        [
            "## Optional Agent Guidance",
            _fenced_text(agent_guidance.strip()),
        ]
    )


def _rubric_score_table(assessment: AssessmentResultDTO) -> str:
    rows = ["| Rubric | Score | Confidence | Evidence |", "| --- | ---: | ---: | --- |"]
    for rubric_id, score in assessment.rubric_scores.items():
        rows.append(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(rubric_id),
                    str(score.score),
                    str(score.confidence),
                    _escape_table_cell("; ".join(score.evidence) or "none"),
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def _feedback_items(assessment: AssessmentResultDTO) -> str:
    if not assessment.feedback_items:
        return "- none"
    return "\n".join(
        (
            f"- `{_inline_markdown(item.category)}`: {_inline_markdown(item.message)}"
            + (
                " Evidence: "
                + "; ".join(_inline_markdown(evidence) for evidence in item.evidence)
                if item.evidence
                else ""
            )
        )
        for item in assessment.feedback_items
    )


def _markdown_list(items: Sequence[str]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {_inline_markdown(item)}" for item in items)


def _escape_table_cell(value: str) -> str:
    return _inline_markdown(value)


def _inline_markdown(value: str) -> str:
    normalized = _redact_local_paths(" ".join(str(value).splitlines()).strip())
    return (
        normalized
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("#", "\\#")
        .replace("|", "\\|")
    )


def _fenced_text(value: str) -> str:
    redacted = _redact_local_paths(value)
    return "```text\n" + redacted.replace("```", "`\u200b``") + "\n```"


def _redact_local_paths(value: str) -> str:
    value = _POSIX_LOCAL_PATH_RE.sub(_redacted_posix_path, value)
    return _WINDOWS_LOCAL_PATH_RE.sub(_redacted_windows_path, value)


def _redacted_posix_path(match: re.Match[str]) -> str:
    return _redacted_path(match.group(0), separator="/")


def _redacted_windows_path(match: re.Match[str]) -> str:
    return _redacted_path(match.group(0), separator="\\")


def _redacted_path(path: str, *, separator: str) -> str:
    stripped = path.rstrip(separator)
    parts = [part for part in stripped.split(separator) if part]
    if not parts or _is_bare_home_path(parts, separator):
        return "<local-path>"
    basename = parts[-1]
    return f"<local-path>{separator}{basename}"


def _is_bare_home_path(parts: list[str], separator: str) -> bool:
    if separator == "/":
        return len(parts) <= 2 and parts[0] in {"Users", "home"}
    if separator == "\\":
        return (
            len(parts) <= 3
            and len(parts[0]) == 2
            and parts[0][1] == ":"
            and parts[1].lower() == "users"
        )
    return False


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_name = temp_file.name
        os.replace(temp_name, path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
