from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from rust_sensei.domain.enums import Difficulty, WorkspaceArtifactPolicy

VALID_RUBRIC_IDS = {
    "rust_correctness",
    "rust_idioms",
    "readability",
    "maintainability",
    "problem_solving",
    "dsa",
    "compiler_error_handling",
}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_DIFFICULTIES = {difficulty.value for difficulty in Difficulty}


@dataclass(frozen=True)
class LessonCommand:
    command: str
    purpose: str
    risk_level: str
    required: bool = True
    allowed_for_agent_verification: bool = False


@dataclass(frozen=True)
class LessonVariant:
    variant_id: str
    difficulty: str
    prompt: str
    success_criteria: list[str]
    hints: list[str] = field(default_factory=list)
    lesson_commands: list[LessonCommand] = field(default_factory=list)
    workspace_artifact_policy: WorkspaceArtifactPolicy = (
        WorkspaceArtifactPolicy.CARGO_BINARY_PACKAGE
    )


@dataclass(frozen=True)
class Concept:
    concept_id: str
    title: str
    order: int
    default_difficulty: str
    learner_command: str | None
    rubric_ids: list[str]
    variants: list[LessonVariant]
    prerequisites: list[str] = field(default_factory=list)
    competency_goals: list[str] = field(default_factory=list)
    baseline_task: str | None = None
    stretch_signals: list[str] = field(default_factory=list)
    struggle_signals: list[str] = field(default_factory=list)
    next_concepts: list[str] = field(default_factory=list)
    branch_targets: dict[str, list[str]] = field(default_factory=dict)
    completion_thresholds: dict[str, float] = field(default_factory=dict)

    def default_variant(self) -> LessonVariant:
        variant = next(
            (
                variant
                for variant in self.variants
                if variant.difficulty == self.default_difficulty
            ),
            None,
        )
        if variant is None:
            raise ValueError(
                f"Concept {self.concept_id} has no variant for default difficulty "
                f"{self.default_difficulty}"
            )
        return variant


@dataclass(frozen=True)
class Curriculum:
    curriculum_version: str
    concepts: dict[str, Concept]
    branch_fallbacks: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Curriculum":
        source = _require_mapping(data, "curriculum")
        concepts_data = _require_list(source, "concepts")
        if not concepts_data:
            raise ValueError("Curriculum must define at least 1 concept")

        concepts = [
            _concept_from_dict(_require_mapping(item, f"concepts[{index}]"))
            for index, item in enumerate(concepts_data)
        ]
        _validate_unique("concept_id", [concept.concept_id for concept in concepts])
        curriculum = cls(
            curriculum_version=_require_text(source, "curriculum_version"),
            concepts={concept.concept_id: concept for concept in concepts},
            branch_fallbacks=_branch_targets_from_mapping(
                _optional_mapping(source, "branch_fallbacks"),
                "branch_fallbacks",
            ),
        )
        _validate_curriculum(curriculum)
        return curriculum


def _concept_from_dict(data: dict[str, Any]) -> Concept:
    concept_id = _require_text(data, "concept_id")
    label = f"concept {concept_id}"
    return Concept(
        concept_id=concept_id,
        title=_require_text(data, "title"),
        order=_require_int(data, "order"),
        prerequisites=_optional_string_list(data, "prerequisites"),
        default_difficulty=_require_text(data, "default_difficulty"),
        competency_goals=_optional_string_list(data, "competency_goals"),
        baseline_task=_optional_text(data, "baseline_task"),
        learner_command=_optional_text(data, "learner_command"),
        stretch_signals=_optional_string_list(data, "stretch_signals"),
        struggle_signals=_optional_string_list(data, "struggle_signals"),
        rubric_ids=_require_string_list(data, "rubric_ids"),
        variants=[
            _variant_from_dict(
                _require_mapping(item, f"{label}.variants[{index}]"),
                label,
                index,
            )
            for index, item in enumerate(_require_list(data, "variants"))
        ],
        next_concepts=_optional_string_list(data, "next_concepts"),
        branch_targets=_branch_targets_from_mapping(
            _optional_mapping(data, "branch_targets"),
            f"{label}.branch_targets",
        ),
        completion_thresholds=_completion_thresholds_from_mapping(
            _optional_mapping(data, "completion_thresholds"),
            f"{label}.completion_thresholds",
        ),
    )


def _variant_from_dict(
    data: dict[str, Any],
    concept_label: str,
    index: int,
) -> LessonVariant:
    label = f"{concept_label}.variants[{index}]"
    return LessonVariant(
        variant_id=_require_text(data, "variant_id"),
        difficulty=_require_text(data, "difficulty"),
        prompt=_require_text(data, "prompt"),
        success_criteria=_require_string_list(data, "success_criteria"),
        hints=_optional_string_list(data, "hints"),
        lesson_commands=[
            _command_from_dict(
                _require_mapping(item, f"{label}.lesson_commands[{command_index}]"),
            )
            for command_index, item in enumerate(
                _optional_list(data, "lesson_commands")
            )
        ],
        workspace_artifact_policy=_workspace_artifact_policy_from_mapping(data, label),
    )


def _command_from_dict(data: dict[str, Any]) -> LessonCommand:
    return LessonCommand(
        command=_require_text(data, "command"),
        purpose=_require_text(data, "purpose"),
        risk_level=_require_text(data, "risk_level"),
        required=_optional_bool(data, "required", default=True),
        allowed_for_agent_verification=_optional_bool(
            data,
            "allowed_for_agent_verification",
            default=False,
        ),
    )


def _validate_curriculum(curriculum: Curriculum) -> None:
    _validate_unique(
        "concept order",
        [str(concept.order) for concept in curriculum.concepts.values()],
    )
    for concept in curriculum.concepts.values():
        if not concept.variants:
            raise ValueError(f"Concept {concept.concept_id} must define at least 1 variant")
        if concept.default_difficulty not in VALID_DIFFICULTIES:
            raise ValueError(
                f"Concept {concept.concept_id} has invalid default difficulty "
                f"{concept.default_difficulty}"
            )

        _validate_unique(
            f"{concept.concept_id}.variant_id",
            [variant.variant_id for variant in concept.variants],
        )
        _validate_rubrics(concept)
        _validate_commands(concept)
        concept.default_variant()
        _validate_concept_references(
            curriculum,
            concept.concept_id,
            "prerequisites",
            concept.prerequisites,
        )
        _validate_concept_references(
            curriculum,
            concept.concept_id,
            "next_concepts",
            concept.next_concepts,
        )
        _validate_completion_thresholds(concept)
        _validate_branch_targets(curriculum, concept.branch_targets)
    _validate_branch_targets(curriculum, curriculum.branch_fallbacks)


def _validate_rubrics(concept: Concept) -> None:
    unknown = sorted(set(concept.rubric_ids) - VALID_RUBRIC_IDS)
    if unknown:
        raise ValueError(
            f"Concept {concept.concept_id} references unknown rubric ids: {unknown}"
        )


def _validate_commands(concept: Concept) -> None:
    for variant in concept.variants:
        if variant.difficulty not in VALID_DIFFICULTIES:
            raise ValueError(
                f"Variant {variant.variant_id} has invalid difficulty "
                f"{variant.difficulty}"
            )
        if variant.workspace_artifact_policy not in set(WorkspaceArtifactPolicy):
            raise ValueError(
                f"Variant {variant.variant_id} has invalid workspace artifact policy "
                f"{variant.workspace_artifact_policy}"
            )
        for command in variant.lesson_commands:
            if command.risk_level not in VALID_RISK_LEVELS:
                raise ValueError(
                    f"Variant {variant.variant_id} has invalid risk level "
                    f"{command.risk_level}"
                )
            if not command.command:
                raise ValueError(f"Variant {variant.variant_id} has an empty command")
            if not command.purpose:
                raise ValueError(f"Variant {variant.variant_id} has an empty purpose")


def _validate_concept_references(
    curriculum: Curriculum,
    concept_id: str,
    field_name: str,
    target_ids: list[str],
) -> None:
    missing = [
        target_id
        for target_id in target_ids
        if target_id not in curriculum.concepts
    ]
    if missing:
        raise ValueError(
            f"Concept {concept_id} {field_name} reference unknown concepts: {missing}"
        )


def _validate_completion_thresholds(concept: Concept) -> None:
    unknown = sorted(set(concept.completion_thresholds) - set(concept.rubric_ids))
    if unknown:
        raise ValueError(
            f"Concept {concept.concept_id} completion thresholds reference "
            f"rubrics not used by the concept: {unknown}"
        )


def _validate_branch_targets(
    curriculum: Curriculum,
    branch_targets: dict[str, list[str]],
) -> None:
    for branch_id, concept_ids in branch_targets.items():
        if not branch_id:
            raise ValueError("Branch target ids must not be empty")
        if not concept_ids:
            raise ValueError(f"Branch target {branch_id} must define at least 1 concept")

        missing = [
            concept_id
            for concept_id in concept_ids
            if concept_id not in curriculum.concepts
        ]
        if missing:
            raise ValueError(
                f"Branch target {branch_id} references unknown concepts: {missing}"
            )


def _validate_unique(label: str, values: list[str]) -> None:
    seen = set()
    duplicates = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        else:
            seen.add(value)
    if duplicates:
        raise ValueError(f"Duplicate {label} values: {sorted(set(duplicates))}")


def _workspace_artifact_policy_from_mapping(
    data: dict[str, Any],
    label: str,
) -> WorkspaceArtifactPolicy:
    value = data.get(
        "workspace_artifact_policy",
        WorkspaceArtifactPolicy.CARGO_BINARY_PACKAGE.value,
    )
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.workspace_artifact_policy must be a non-empty string")
    try:
        return WorkspaceArtifactPolicy(value)
    except ValueError as exc:
        raise ValueError(
            f"{label}.workspace_artifact_policy has invalid value {value!r}"
        ) from exc


def _branch_targets_from_mapping(
    data: dict[str, Any],
    label: str,
) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    for branch_id, concept_ids in data.items():
        if not isinstance(branch_id, str) or not branch_id.strip():
            raise ValueError(f"{label} keys must be non-empty strings")
        targets[branch_id] = _string_list_from_value(
            concept_ids,
            f"{label}.{branch_id}",
            allow_empty=False,
        )
    return targets


def _completion_thresholds_from_mapping(
    data: dict[str, Any],
    label: str,
) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for rubric_id, threshold in data.items():
        if not isinstance(rubric_id, str) or not rubric_id.strip():
            raise ValueError(f"{label} keys must be non-empty strings")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError(f"{label}.{rubric_id} must be a number")
        threshold_value = float(threshold)
        if not math.isfinite(threshold_value):
            raise ValueError(f"{label}.{rubric_id} must be a finite number")
        if threshold_value < 0.0 or threshold_value > 1.0:
            raise ValueError(f"{label}.{rubric_id} must be between 0.0 and 1.0")
        thresholds[rubric_id] = threshold_value
    return thresholds


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _optional_mapping(data: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = data.get(field_name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_list(data: dict[str, Any], field_name: str) -> list[Any]:
    if field_name not in data:
        raise ValueError(f"{field_name} is required")
    return _list_from_value(data[field_name], field_name)


def _optional_list(data: dict[str, Any], field_name: str) -> list[Any]:
    return _list_from_value(data.get(field_name, []), field_name)


def _list_from_value(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _require_text(data: dict[str, Any], field_name: str) -> str:
    if field_name not in data:
        raise ValueError(f"{field_name} is required")
    value = data[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(data: dict[str, Any], field_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided")
    return value


def _require_int(data: dict[str, Any], field_name: str) -> int:
    if field_name not in data:
        raise ValueError(f"{field_name} is required")
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_bool(data: dict[str, Any], field_name: str, *, default: bool) -> bool:
    key = field_name.rsplit(".", 1)[-1]
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_string_list(data: dict[str, Any], field_name: str) -> list[str]:
    if field_name not in data:
        raise ValueError(f"{field_name} is required")
    return _string_list_from_value(data[field_name], field_name, allow_empty=False)


def _optional_string_list(data: dict[str, Any], field_name: str) -> list[str]:
    return _string_list_from_value(data.get(field_name, []), field_name, allow_empty=True)


def _string_list_from_value(
    value: Any,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    values = _list_from_value(value, label)
    if not values and not allow_empty:
        raise ValueError(f"{label} must contain at least 1 item")
    for index, item in enumerate(values):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label}[{index}] must be a non-empty string")
    return list(values)
