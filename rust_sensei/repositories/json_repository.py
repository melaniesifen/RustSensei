from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rust_sensei.constants import STATE_FILE_NAME
from rust_sensei.domain.curriculum import Concept, Curriculum
from rust_sensei.domain.enums import AssignmentStatus, RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.skill import SkillModel, SkillScore
from rust_sensei.errors import storage_error
from rust_sensei.repositories.json_state import JsonStateStore


class JsonLearnerRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def get_active_profile(self) -> LearnerProfile | None:
        state = self._store.read()
        active_learner_id = state["active_learner_id"]
        return self._profile_from_state(state["learners"].get(active_learner_id))

    def get_profile(self, learner_id: str) -> LearnerProfile | None:
        state = self._store.read()
        return self._profile_from_state(state["learners"].get(learner_id))

    def save_profile(self, profile: LearnerProfile) -> None:
        def mutation(state: dict[str, Any]) -> None:
            state["learners"][profile.learner_id] = self._profile_to_state(profile)

        self._store.update(mutation)

    def create_profile_if_absent(self, profile: LearnerProfile) -> LearnerProfile:
        def transaction(state: dict[str, Any]) -> tuple[LearnerProfile, bool]:
            existing = self._profile_from_state(state["learners"].get(profile.learner_id))
            if existing is not None:
                return existing, False

            state["learners"][profile.learner_id] = self._profile_to_state(profile)
            return profile, True

        return self._store.transact(transaction)

    @staticmethod
    def _profile_from_state(data: dict[str, Any] | None) -> LearnerProfile | None:
        if data is None:
            return None

        return LearnerProfile(
            learner_id=data["learner_id"],
            rust_level_initial=RustLevel(data["rust_level_initial"]),
            active_concept_id=data.get("active_concept_id"),
            skill_model=_skill_model_from_state(data["skill_model"]),
            created_at=_parse_datetime(data["created_at"]),
            updated_at=_parse_datetime(data["updated_at"]),
        )

    @staticmethod
    def _profile_to_state(profile: LearnerProfile) -> dict[str, Any]:
        return {
            "learner_id": profile.learner_id,
            "rust_level_initial": profile.rust_level_initial.value,
            "active_concept_id": profile.active_concept_id,
            "skill_model": _skill_model_to_state(profile.skill_model),
            "created_at": _format_datetime(profile.created_at),
            "updated_at": _format_datetime(profile.updated_at),
        }


class JsonAssignmentRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def save_assignment(self, assignment: LessonAssignment) -> None:
        def mutation(state: dict[str, Any]) -> None:
            state["lesson_assignments"] = [
                item
                for item in state["lesson_assignments"]
                if item["assignment_id"] != assignment.assignment_id
            ]
            state["lesson_assignments"].append(_assignment_to_state(assignment))

        self._store.update(mutation)

    def create_active_assignment_if_absent(
        self,
        assignment: LessonAssignment,
    ) -> tuple[LessonAssignment, bool]:
        def transaction(
            state: dict[str, Any],
        ) -> tuple[tuple[LessonAssignment, bool], bool]:
            existing = _active_assignment_from_state(
                state,
                learner_id=assignment.learner_id,
            )
            if existing is not None:
                return (existing, False), False

            created = replace(
                assignment,
                assignment_id=_next_assignment_id(state),
            )
            state["lesson_assignments"].append(_assignment_to_state(created))
            return (created, True), True

        return self._store.transact(transaction)

    def get_assignment(self, assignment_id: str) -> LessonAssignment | None:
        state = self._store.read()
        return next(
            (
                _assignment_from_state(item)
                for item in reversed(state["lesson_assignments"])
                if item["assignment_id"] == assignment_id
            ),
            None,
        )

    def get_active_assignment(self, learner_id: str) -> LessonAssignment | None:
        state = self._store.read()
        return _active_assignment_from_state(state, learner_id)


class JsonCurriculumRepository:
    def __init__(self, curriculum_path: Path) -> None:
        self._curriculum_path = curriculum_path

    def get_curriculum(self) -> Curriculum:
        try:
            with self._curriculum_path.open("r", encoding="utf-8") as curriculum_file:
                return Curriculum.from_dict(json.load(curriculum_file))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise storage_error(
                "Curriculum seed data is invalid",
                retryable=False,
                path=str(self._curriculum_path),
            ) from exc

    def get_concept(self, concept_id: str) -> Concept | None:
        return self.get_curriculum().concepts.get(concept_id)


class JsonRepositoryFactory:
    def __init__(self, state_dir: Path, curriculum_path: Path | None = None) -> None:
        self._state_dir = state_dir
        self._state_store = JsonStateStore(self._state_dir / STATE_FILE_NAME)
        self._curriculum_path = curriculum_path or (
            Path(__file__).resolve().parent.parent / "resources" / "curriculum_seed.json"
        )

    def learner_repository(self) -> JsonLearnerRepository:
        return JsonLearnerRepository(self._state_store)

    def assignment_repository(self) -> JsonAssignmentRepository:
        return JsonAssignmentRepository(self._state_store)

    def curriculum_repository(self) -> JsonCurriculumRepository:
        return JsonCurriculumRepository(self._curriculum_path)


def default_state_dir() -> Path:
    return Path.home() / ".rust-sensei"


def _skill_model_from_state(data: dict[str, Any]) -> SkillModel:
    return SkillModel(
        rust_concepts={
            key: _skill_score_from_state(value)
            for key, value in data.get("rust_concepts", {}).items()
        },
        programming_dimensions={
            key: _skill_score_from_state(value)
            for key, value in data.get("programming_dimensions", {}).items()
        },
    )


def _skill_score_from_state(data: dict[str, Any]) -> SkillScore:
    return SkillScore(
        score=float(data["score"]),
        confidence=float(data["confidence"]),
        evidence=list(data.get("evidence", [])),
    )


def _skill_model_to_state(model: SkillModel) -> dict[str, Any]:
    return {
        "rust_concepts": {
            key: _skill_score_to_state(value)
            for key, value in model.rust_concepts.items()
        },
        "programming_dimensions": {
            key: _skill_score_to_state(value)
            for key, value in model.programming_dimensions.items()
        },
    }


def _skill_score_to_state(score: SkillScore) -> dict[str, Any]:
    return {
        "score": score.score,
        "confidence": score.confidence,
        "evidence": list(score.evidence),
    }


def _assignment_from_state(data: dict[str, Any]) -> LessonAssignment:
    return LessonAssignment(
        assignment_id=data["assignment_id"],
        learner_id=data["learner_id"],
        lesson_id=data["lesson_id"],
        concept_id=data["concept_id"],
        difficulty=data["difficulty"],
        variant_id=data["variant_id"],
        status=AssignmentStatus(data["status"]),
        selection_rationale=data["selection_rationale"],
        curriculum_version=data["curriculum_version"],
        created_at=_parse_datetime(data["created_at"]),
        updated_at=_parse_datetime(data["updated_at"]),
    )


def _assignment_to_state(assignment: LessonAssignment) -> dict[str, Any]:
    return {
        "assignment_id": assignment.assignment_id,
        "learner_id": assignment.learner_id,
        "lesson_id": assignment.lesson_id,
        "concept_id": assignment.concept_id,
        "difficulty": assignment.difficulty,
        "variant_id": assignment.variant_id,
        "status": assignment.status.value,
        "selection_rationale": assignment.selection_rationale,
        "curriculum_version": assignment.curriculum_version,
        "created_at": _format_datetime(assignment.created_at),
        "updated_at": _format_datetime(assignment.updated_at),
    }


def _next_assignment_id(state: dict[str, Any]) -> str:
    next_number = len(state["lesson_assignments"]) + 1
    return f"assign_{next_number:06d}"


def _active_assignment_from_state(
    state: dict[str, Any],
    learner_id: str,
) -> LessonAssignment | None:
    latest_records = []
    seen_assignment_ids = set()
    for item in reversed(state["lesson_assignments"]):
        if item["learner_id"] != learner_id:
            continue
        if item["assignment_id"] in seen_assignment_ids:
            continue
        seen_assignment_ids.add(item["assignment_id"])
        latest_records.append(item)

    return next(
        (
            _assignment_from_state(item)
            for item in latest_records
            if item["status"] == "active"
        ),
        None,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")
