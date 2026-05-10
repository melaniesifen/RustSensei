from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rust_sensei.constants import STATE_FILE_NAME
from rust_sensei.domain.attempt import AttemptSubmission, CommandRunMetadata
from rust_sensei.domain.curriculum import Concept, Curriculum
from rust_sensei.domain.enums import AssignmentStatus, RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.skill import SkillModel, SkillScore
from rust_sensei.errors import idempotency_conflict_error, storage_error
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
            _replace_assignment(state, assignment)

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

    def get_attempted_assignment(self, learner_id: str) -> LessonAssignment | None:
        state = self._store.read()
        return _assignment_with_status_from_state(
            state,
            learner_id=learner_id,
            status=AssignmentStatus.ATTEMPTED,
        )

    def update_assignment(self, assignment: LessonAssignment) -> None:
        self.save_assignment(assignment)


class JsonAttemptRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def save_attempt_for_assignment(
        self,
        attempt: AttemptSubmission,
        assignment: LessonAssignment,
    ) -> tuple[AttemptSubmission, bool]:
        def transaction(
            state: dict[str, Any],
        ) -> tuple[tuple[AttemptSubmission, bool], bool]:
            if attempt.client_request_id is not None:
                existing = _attempt_by_client_request_id_from_state(
                    state,
                    learner_id=attempt.learner_id,
                    client_request_id=attempt.client_request_id,
                )
                if existing is not None:
                    if (
                        existing.client_request_fingerprint
                        != attempt.client_request_fingerprint
                    ):
                        raise idempotency_conflict_error(
                            "client_request_id was reused with different content",
                            client_request_id=attempt.client_request_id,
                        )
                    return (existing, False), False

            created = replace(
                attempt,
                attempt_id=_next_attempt_id(state),
            )
            state["attempts"].append(_attempt_to_state(created))
            _replace_assignment(state, assignment)
            return (created, True), True

        return self._store.transact(transaction)

    def get_attempt(self, attempt_id: str) -> AttemptSubmission | None:
        state = self._store.read()
        return next(
            (
                _attempt_from_state(item)
                for item in reversed(state["attempts"])
                if item["attempt_id"] == attempt_id
            ),
            None,
        )

    def get_attempt_by_client_request_id(
        self,
        learner_id: str,
        client_request_id: str,
    ) -> AttemptSubmission | None:
        state = self._store.read()
        return _attempt_by_client_request_id_from_state(
            state,
            learner_id=learner_id,
            client_request_id=client_request_id,
        )

    def get_latest_attempt_for_assignment(
        self,
        assignment_id: str,
    ) -> AttemptSubmission | None:
        state = self._store.read()
        return next(
            (
                _attempt_from_state(item)
                for item in reversed(state["attempts"])
                if item["assignment_id"] == assignment_id
            ),
            None,
        )


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

    def attempt_repository(self) -> JsonAttemptRepository:
        return JsonAttemptRepository(self._state_store)

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


def _replace_assignment(state: dict[str, Any], assignment: LessonAssignment) -> None:
    state["lesson_assignments"] = [
        item
        for item in state["lesson_assignments"]
        if item["assignment_id"] != assignment.assignment_id
    ]
    state["lesson_assignments"].append(_assignment_to_state(assignment))


def _next_assignment_id(state: dict[str, Any]) -> str:
    next_number = len(state["lesson_assignments"]) + 1
    return f"assign_{next_number:06d}"


def _next_attempt_id(state: dict[str, Any]) -> str:
    next_number = len(state["attempts"]) + 1
    return f"attempt_{next_number:06d}"


def _attempt_from_state(data: dict[str, Any]) -> AttemptSubmission:
    return AttemptSubmission(
        attempt_id=data["attempt_id"],
        learner_id=data["learner_id"],
        assignment_id=data["assignment_id"],
        lesson_id=data["lesson_id"],
        client_request_id=data.get("client_request_id"),
        client_request_fingerprint=data.get("client_request_fingerprint"),
        workspace_root=data.get("workspace_root"),
        code=data.get("code"),
        file_paths=list(data.get("file_paths", [])),
        commands_run_by_learner=list(data.get("commands_run_by_learner", [])),
        verification_commands_run_by_agent=list(
            data.get("verification_commands_run_by_agent", [])
        ),
        compiler_output=data.get("compiler_output"),
        runtime_output=data.get("runtime_output"),
        test_output=data.get("test_output"),
        command_run_metadata=[
            _command_metadata_from_state(item)
            for item in data.get("command_run_metadata", [])
        ],
        output_truncated=bool(data.get("output_truncated", False)),
        truncation_reason=data.get("truncation_reason"),
        omitted_files=list(data.get("omitted_files", [])),
        learner_notes=data.get("learner_notes"),
        agent_notes=data.get("agent_notes"),
        learner_execution_missing=bool(data.get("learner_execution_missing", False)),
        learner_execution_notes=data.get("learner_execution_notes"),
        submitted_at=_parse_datetime(data["submitted_at"]),
    )


def _attempt_to_state(attempt: AttemptSubmission) -> dict[str, Any]:
    if attempt.submitted_at is None:
        raise ValueError("submitted_at is required before persisting an attempt")

    return {
        "attempt_id": attempt.attempt_id,
        "learner_id": attempt.learner_id,
        "assignment_id": attempt.assignment_id,
        "lesson_id": attempt.lesson_id,
        "client_request_id": attempt.client_request_id,
        "client_request_fingerprint": attempt.client_request_fingerprint,
        "workspace_root": attempt.workspace_root,
        "code": attempt.code,
        "file_paths": list(attempt.file_paths),
        "commands_run_by_learner": list(attempt.commands_run_by_learner),
        "verification_commands_run_by_agent": list(
            attempt.verification_commands_run_by_agent
        ),
        "compiler_output": attempt.compiler_output,
        "runtime_output": attempt.runtime_output,
        "test_output": attempt.test_output,
        "command_run_metadata": [
            _command_metadata_to_state(item)
            for item in attempt.command_run_metadata
        ],
        "output_truncated": attempt.output_truncated,
        "truncation_reason": attempt.truncation_reason,
        "omitted_files": list(attempt.omitted_files),
        "learner_notes": attempt.learner_notes,
        "agent_notes": attempt.agent_notes,
        "learner_execution_missing": attempt.learner_execution_missing,
        "learner_execution_notes": attempt.learner_execution_notes,
        "submitted_at": _format_datetime(attempt.submitted_at),
    }


def _command_metadata_from_state(data: dict[str, Any]) -> CommandRunMetadata:
    return CommandRunMetadata(
        command=data["command"],
        source=data["source"],
        cwd=data.get("cwd"),
        exit_code=data.get("exit_code"),
        started_at=_parse_datetime(data["started_at"]),
        duration_ms=data.get("duration_ms"),
        timed_out=bool(data.get("timed_out", False)),
        timeout_ms=data.get("timeout_ms"),
        output_summary=data.get("output_summary"),
        output_truncated=bool(data.get("output_truncated", False)),
        stdout_truncated=bool(data.get("stdout_truncated", False)),
        stderr_truncated=bool(data.get("stderr_truncated", False)),
        purpose=data.get("purpose"),
        risk_level=data.get("risk_level"),
    )


def _command_metadata_to_state(metadata: CommandRunMetadata) -> dict[str, Any]:
    return {
        "command": metadata.command,
        "source": metadata.source,
        "cwd": metadata.cwd,
        "exit_code": metadata.exit_code,
        "started_at": _format_datetime(metadata.started_at),
        "duration_ms": metadata.duration_ms,
        "timed_out": metadata.timed_out,
        "timeout_ms": metadata.timeout_ms,
        "output_summary": metadata.output_summary,
        "output_truncated": metadata.output_truncated,
        "stdout_truncated": metadata.stdout_truncated,
        "stderr_truncated": metadata.stderr_truncated,
        "purpose": metadata.purpose,
        "risk_level": metadata.risk_level,
    }



def _active_assignment_from_state(
    state: dict[str, Any],
    learner_id: str,
) -> LessonAssignment | None:
    return _assignment_with_status_from_state(
        state,
        learner_id=learner_id,
        status=AssignmentStatus.ACTIVE,
    )


def _assignment_with_status_from_state(
    state: dict[str, Any],
    learner_id: str,
    status: AssignmentStatus,
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
            if item["status"] == status.value
        ),
        None,
    )


def _attempt_by_client_request_id_from_state(
    state: dict[str, Any],
    learner_id: str,
    client_request_id: str,
) -> AttemptSubmission | None:
    return next(
        (
            _attempt_from_state(item)
            for item in reversed(state["attempts"])
            if item["learner_id"] == learner_id
            and item.get("client_request_id") == client_request_id
        ),
        None,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")
