from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rust_sensei.constants import STATE_FILE_NAME
from rust_sensei.domain.enums import RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.skill import SkillModel, SkillScore
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


class JsonRepositoryFactory:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def learner_repository(self) -> JsonLearnerRepository:
        return JsonLearnerRepository(JsonStateStore(self._state_dir / STATE_FILE_NAME))


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


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")
