from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rust_sensei.domain.enums import WorkspaceArtifactPolicy

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
    branch_targets: dict[str, list[str]] = field(default_factory=dict)

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
        concepts = [_concept_from_dict(item) for item in data["concepts"]]
        _validate_unique("concept_id", [concept.concept_id for concept in concepts])
        curriculum = cls(
            curriculum_version=data["curriculum_version"],
            concepts={concept.concept_id: concept for concept in concepts},
            branch_fallbacks={
                key: list(value)
                for key, value in data.get("branch_fallbacks", {}).items()
            },
        )
        _validate_curriculum(curriculum)
        return curriculum


def _concept_from_dict(data: dict[str, Any]) -> Concept:
    return Concept(
        concept_id=data["concept_id"],
        title=data["title"],
        order=int(data["order"]),
        default_difficulty=data["default_difficulty"],
        learner_command=data.get("learner_command"),
        rubric_ids=list(data["rubric_ids"]),
        variants=[_variant_from_dict(item) for item in data["variants"]],
        branch_targets={
            key: list(value)
            for key, value in data.get("branch_targets", {}).items()
        },
    )


def _variant_from_dict(data: dict[str, Any]) -> LessonVariant:
    return LessonVariant(
        variant_id=data["variant_id"],
        difficulty=data["difficulty"],
        prompt=data["prompt"],
        success_criteria=list(data["success_criteria"]),
        hints=list(data.get("hints", [])),
        lesson_commands=[
            LessonCommand(
                command=item["command"],
                purpose=item["purpose"],
                risk_level=item["risk_level"],
                required=bool(item.get("required", True)),
                allowed_for_agent_verification=bool(
                    item.get("allowed_for_agent_verification", False)
                ),
            )
            for item in data.get("lesson_commands", [])
        ],
        workspace_artifact_policy=WorkspaceArtifactPolicy(
            data.get(
                "workspace_artifact_policy",
                WorkspaceArtifactPolicy.CARGO_BINARY_PACKAGE.value,
            )
        ),
    )


def _validate_curriculum(curriculum: Curriculum) -> None:
    for concept in curriculum.concepts.values():
        if not concept.variants:
            raise ValueError(f"Concept {concept.concept_id} must define at least 1 variant")

        _validate_unique(
            f"{concept.concept_id}.variant_id",
            [variant.variant_id for variant in concept.variants],
        )
        concept.default_variant()
        _validate_rubrics(concept)
        _validate_commands(concept)
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
