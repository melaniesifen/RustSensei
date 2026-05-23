from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from rust_sensei.constants import STATE_FILE_NAME
from rust_sensei.domain.assessment import (
    AssessmentResult,
    AssessmentScoringProvenance,
    ConfidenceBreakdown,
    FeedbackItem,
)
from rust_sensei.domain.attempt import AttemptSubmission, CommandRunMetadata
from rust_sensei.domain.curriculum import Concept, Curriculum
from rust_sensei.domain.enums import (
    AssignmentStatus,
    LearnerSignalType,
    NextAction,
    RustLevel,
)
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.domain.signal import LearnerSignal
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

    def create_profile_if_absent(
        self,
        profile: LearnerProfile,
        event_factory: (
            Callable[[LearnerProfile], Iterable[ProgressEvent]] | None
        ) = None,
    ) -> LearnerProfile:
        def transaction(state: dict[str, Any]) -> tuple[LearnerProfile, bool]:
            existing = self._profile_from_state(
                state["learners"].get(profile.learner_id)
            )
            if existing is not None:
                return existing, False

            state["learners"][profile.learner_id] = self._profile_to_state(profile)
            if event_factory is not None:
                for event in event_factory(profile):
                    _append_progress_event(state, event)
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
        event_factory: Callable[[LessonAssignment], ProgressEvent] | None = None,
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
            if event_factory is not None:
                _append_progress_event(state, event_factory(created))
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

    def get_latest_assessed_assignment(
        self,
        learner_id: str,
    ) -> LessonAssignment | None:
        state = self._store.read()
        return _assignment_with_status_from_state(
            state,
            learner_id=learner_id,
            status=AssignmentStatus.ASSESSED,
        )

    def list_assignments_for_learner(
        self,
        learner_id: str,
    ) -> list[LessonAssignment]:
        state = self._store.read()
        return [
            _assignment_from_state(item)
            for item in state["lesson_assignments"]
            if item["learner_id"] == learner_id
        ]

    def update_assignment(
        self,
        assignment: LessonAssignment,
        event_factory: Callable[[LessonAssignment], ProgressEvent] | None = None,
    ) -> None:
        def mutation(state: dict[str, Any]) -> None:
            _replace_assignment(state, assignment)
            if event_factory is not None:
                _append_progress_event(state, event_factory(assignment))

        self._store.update(mutation)


class JsonAttemptRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def save_attempt_for_assignment(
        self,
        attempt: AttemptSubmission,
        assignment: LessonAssignment,
        event_factory: Callable[[AttemptSubmission], ProgressEvent] | None = None,
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
            if event_factory is not None:
                _append_progress_event(state, event_factory(created))
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


class JsonAssessmentRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def save_assessment_for_assignment(
        self,
        result: AssessmentResult,
        assignment: LessonAssignment,
        event_factory: Callable[[AssessmentResult], ProgressEvent] | None = None,
    ) -> tuple[AssessmentResult, bool]:
        return self.save_assessment_for_assignment_and_profile(
            result=result,
            assignment=assignment,
            profile_updater=None,
            event_factory=event_factory,
        )

    def save_assessment_for_assignment_and_profile(
        self,
        result: AssessmentResult,
        assignment: LessonAssignment,
        profile_updater: (
            Callable[[AssessmentResult, LearnerProfile], LearnerProfile] | None
        ),
        event_factory: Callable[[AssessmentResult], ProgressEvent] | None = None,
    ) -> tuple[AssessmentResult, bool]:
        def transaction(
            state: dict[str, Any],
        ) -> tuple[tuple[AssessmentResult, bool], bool]:
            existing = _assessment_by_attempt_id_from_state(
                state,
                result.attempt_id,
            )
            if existing is not None:
                return (existing, False), False

            created = replace(
                result,
                assessment_id=_next_assessment_id(state),
            )
            state["assessments"].append(_assessment_to_state(created))
            _replace_assignment(state, assignment)
            if profile_updater is not None:
                current_profile = JsonLearnerRepository._profile_from_state(
                    state["learners"].get(assignment.learner_id)
                )
                if current_profile is None:
                    raise storage_error(
                        "Learner profile was not found during assessment save",
                        retryable=True,
                        learner_id=assignment.learner_id,
                    )
                profile = profile_updater(created, current_profile)
                state["learners"][profile.learner_id] = (
                    JsonLearnerRepository._profile_to_state(profile)
                )
            if event_factory is not None:
                _append_progress_event(state, event_factory(created))
            return (created, True), True

        return self._store.transact(transaction)

    def get_assessment_by_attempt_id(
        self,
        attempt_id: str,
    ) -> AssessmentResult | None:
        state = self._store.read()
        return _assessment_by_attempt_id_from_state(state, attempt_id)

    def get_latest_assessment_for_assignment(
        self,
        assignment_id: str,
    ) -> AssessmentResult | None:
        state = self._store.read()
        return next(
            (
                _assessment_from_state(item)
                for item in reversed(state["assessments"])
                if item["assignment_id"] == assignment_id
            ),
            None,
        )

    def list_assessments_for_assignments(
        self,
        assignment_ids: set[str],
    ) -> list[AssessmentResult]:
        state = self._store.read()
        return [
            _assessment_from_state(item)
            for item in state["assessments"]
            if item["assignment_id"] in assignment_ids
        ]


CURRICULUM_RESOURCE_PACKAGE = "rust_sensei.resources"
CURRICULUM_RESOURCE_NAME = "curriculum_seed.json"


class JsonCurriculumRepository:
    def __init__(self, curriculum_path: Path | None = None) -> None:
        self._curriculum_path = curriculum_path

    def get_curriculum(self) -> Curriculum:
        try:
            return Curriculum.from_dict(self._load_curriculum_data())
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise storage_error(
                "Curriculum seed data is invalid",
                retryable=False,
                path=self._curriculum_source_label(),
            ) from exc

    def get_concept(self, concept_id: str) -> Concept | None:
        return self.get_curriculum().concepts.get(concept_id)

    def _load_curriculum_data(self) -> dict[str, Any]:
        if self._curriculum_path is not None:
            with self._curriculum_path.open("r", encoding="utf-8") as curriculum_file:
                return json.load(curriculum_file)

        return json.loads(
            resources.files(CURRICULUM_RESOURCE_PACKAGE)
            .joinpath(CURRICULUM_RESOURCE_NAME)
            .read_text(encoding="utf-8")
        )

    def _curriculum_source_label(self) -> str:
        if self._curriculum_path is not None:
            return str(self._curriculum_path)

        return f"{CURRICULUM_RESOURCE_PACKAGE}/{CURRICULUM_RESOURCE_NAME}"


class JsonProgressEventRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def save_event(self, event: ProgressEvent) -> ProgressEvent:
        def transaction(state: dict[str, Any]) -> tuple[ProgressEvent, bool]:
            return _append_progress_event(state, event), True

        return self._store.transact(transaction)

    def list_recent_events(
        self,
        learner_id: str,
        limit: int,
    ) -> list[ProgressEvent]:
        return self.list_events_for_learner(learner_id)[:limit]

    def list_events_for_learner(
        self,
        learner_id: str,
    ) -> list[ProgressEvent]:
        state = self._store.read()
        return [
            _progress_event_from_state(item)
            for item in reversed(state["progress_events"])
            if item["learner_id"] == learner_id
        ]


class JsonLearnerSignalRepository:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def save_signal(self, signal: LearnerSignal) -> LearnerSignal:
        def transaction(state: dict[str, Any]) -> tuple[LearnerSignal, bool]:
            created = replace(signal, signal_id=_next_signal_id(state))
            state["signals"].append(_signal_to_state(created))
            return created, True

        return self._store.transact(transaction)

    def list_recent_signals(
        self,
        learner_id: str,
        limit: int,
    ) -> list[LearnerSignal]:
        state = self._store.read()
        signals = [
            _signal_from_state(item)
            for item in reversed(state["signals"])
            if item["learner_id"] == learner_id
        ]
        return signals[:limit]


class JsonRepositoryFactory:
    def __init__(self, state_dir: Path, curriculum_path: Path | None = None) -> None:
        self._state_dir = state_dir
        self._state_store = JsonStateStore(self._state_dir / STATE_FILE_NAME)
        self._curriculum_path = curriculum_path

    def learner_repository(self) -> JsonLearnerRepository:
        return JsonLearnerRepository(self._state_store)

    def assignment_repository(self) -> JsonAssignmentRepository:
        return JsonAssignmentRepository(self._state_store)

    def attempt_repository(self) -> JsonAttemptRepository:
        return JsonAttemptRepository(self._state_store)

    def assessment_repository(self) -> JsonAssessmentRepository:
        return JsonAssessmentRepository(self._state_store)

    def curriculum_repository(self) -> JsonCurriculumRepository:
        return JsonCurriculumRepository(self._curriculum_path)

    def progress_event_repository(self) -> JsonProgressEventRepository:
        return JsonProgressEventRepository(self._state_store)

    def learner_signal_repository(self) -> JsonLearnerSignalRepository:
        return JsonLearnerSignalRepository(self._state_store)


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


def _next_assessment_id(state: dict[str, Any]) -> str:
    next_number = len(state["assessments"]) + 1
    return f"assessment_{next_number:06d}"


def _next_progress_event_id(state: dict[str, Any]) -> str:
    next_number = len(state["progress_events"]) + 1
    return f"event_{next_number:06d}"


def _next_signal_id(state: dict[str, Any]) -> str:
    next_number = len(state["signals"]) + 1
    return f"signal_{next_number:06d}"


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


def _assessment_from_state(data: dict[str, Any]) -> AssessmentResult:
    return AssessmentResult(
        assessment_id=data["assessment_id"],
        attempt_id=data["attempt_id"],
        assignment_id=data["assignment_id"],
        scoring_version=data["scoring_version"],
        scoring_provenance=_scoring_provenance_from_state(
            data.get("scoring_provenance")
        ),
        assessment_status=data["assessment_status"],
        rubric_scores={
            key: _skill_score_from_state(value)
            for key, value in data.get("rubric_scores", {}).items()
        },
        confidence_breakdown=_confidence_breakdown_from_state(
            data["confidence_breakdown"]
        ),
        missing_evidence=list(data.get("missing_evidence", [])),
        feedback_items=[
            _feedback_item_from_state(item)
            for item in data.get("feedback_items", [])
        ],
        next_action=NextAction(data["next_action"]),
        branch_id=data.get("branch_id"),
        next_action_reason=data["next_action_reason"],
        feedback_summary=data["feedback_summary"],
        confidence=float(data["confidence"]),
        created_at=_parse_datetime(data["created_at"]),
    )


def _assessment_to_state(result: AssessmentResult) -> dict[str, Any]:
    return {
        "assessment_id": result.assessment_id,
        "attempt_id": result.attempt_id,
        "assignment_id": result.assignment_id,
        "scoring_version": result.scoring_version,
        "scoring_provenance": _scoring_provenance_to_state(
            result.scoring_provenance
        ),
        "assessment_status": result.assessment_status,
        "rubric_scores": {
            key: _skill_score_to_state(value)
            for key, value in result.rubric_scores.items()
        },
        "confidence_breakdown": _confidence_breakdown_to_state(
            result.confidence_breakdown
        ),
        "missing_evidence": list(result.missing_evidence),
        "feedback_items": [
            _feedback_item_to_state(item)
            for item in result.feedback_items
        ],
        "next_action": result.next_action.value,
        "branch_id": result.branch_id,
        "next_action_reason": result.next_action_reason,
        "feedback_summary": result.feedback_summary,
        "confidence": result.confidence,
        "created_at": _format_datetime(result.created_at),
    }


def _scoring_provenance_from_state(
    data: dict[str, Any] | None,
) -> AssessmentScoringProvenance | None:
    if data is None:
        return None

    return AssessmentScoringProvenance(
        scorer_type=data["scorer_type"],
        scorer_name=data["scorer_name"],
        scorer_version=data["scorer_version"],
        model_provider=data.get("model_provider"),
        model_name=data.get("model_name"),
        model_version=data.get("model_version"),
    )


def _scoring_provenance_to_state(
    provenance: AssessmentScoringProvenance | None,
) -> dict[str, Any] | None:
    if provenance is None:
        return None

    return {
        "scorer_type": provenance.scorer_type,
        "scorer_name": provenance.scorer_name,
        "scorer_version": provenance.scorer_version,
        "model_provider": provenance.model_provider,
        "model_name": provenance.model_name,
        "model_version": provenance.model_version,
    }


def _confidence_breakdown_from_state(data: dict[str, Any]) -> ConfidenceBreakdown:
    return ConfidenceBreakdown(
        critical_evidence_cap=(
            None
            if data.get("critical_evidence_cap") is None
            else float(data["critical_evidence_cap"])
        ),
        evidence_completeness=float(data["evidence_completeness"]),
        evidence_quality=float(data["evidence_quality"]),
        rubric_confidences={
            key: float(value)
            for key, value in data.get("rubric_confidences", {}).items()
        },
        prior_consistency=float(data["prior_consistency"]),
        task_difficulty_weight=float(data["task_difficulty_weight"]),
        recency_weight=float(data["recency_weight"]),
        overall=float(data["overall"]),
        explanation=list(data.get("explanation", [])),
    )


def _confidence_breakdown_to_state(
    breakdown: ConfidenceBreakdown,
) -> dict[str, Any]:
    return {
        "critical_evidence_cap": breakdown.critical_evidence_cap,
        "evidence_completeness": breakdown.evidence_completeness,
        "evidence_quality": breakdown.evidence_quality,
        "rubric_confidences": dict(breakdown.rubric_confidences),
        "prior_consistency": breakdown.prior_consistency,
        "task_difficulty_weight": breakdown.task_difficulty_weight,
        "recency_weight": breakdown.recency_weight,
        "overall": breakdown.overall,
        "explanation": list(breakdown.explanation),
    }


def _feedback_item_from_state(data: dict[str, Any]) -> FeedbackItem:
    return FeedbackItem(
        category=data["category"],
        message=data["message"],
        evidence=list(data.get("evidence", [])),
    )


def _feedback_item_to_state(item: FeedbackItem) -> dict[str, Any]:
    return {
        "category": item.category,
        "message": item.message,
        "evidence": list(item.evidence),
    }


def _assessment_by_attempt_id_from_state(
    state: dict[str, Any],
    attempt_id: str,
) -> AssessmentResult | None:
    return next(
        (
            _assessment_from_state(item)
            for item in reversed(state["assessments"])
            if item["attempt_id"] == attempt_id
        ),
        None,
    )


def _progress_event_from_state(data: dict[str, Any]) -> ProgressEvent:
    return ProgressEvent(
        event_id=data["event_id"],
        learner_id=data["learner_id"],
        event_type=ProgressEventType(data["event_type"]),
        assignment_id=data.get("assignment_id"),
        attempt_id=data.get("attempt_id"),
        assessment_id=data.get("assessment_id"),
        details=dict(data.get("details", {})),
        previous_status=data.get("previous_status"),
        new_status=data.get("new_status"),
        created_at=_parse_datetime(data["created_at"]),
    )


def _progress_event_to_state(event: ProgressEvent) -> dict[str, Any]:
    if event.created_at is None:
        raise ValueError("created_at is required before persisting a progress event")

    return {
        "event_id": event.event_id,
        "learner_id": event.learner_id,
        "event_type": event.event_type.value,
        "assignment_id": event.assignment_id,
        "attempt_id": event.attempt_id,
        "assessment_id": event.assessment_id,
        "details": dict(event.details),
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "created_at": _format_datetime(event.created_at),
    }


def _append_progress_event(
    state: dict[str, Any],
    event: ProgressEvent,
) -> ProgressEvent:
    created = replace(
        event,
        event_id=_next_progress_event_id(state),
    )
    state["progress_events"].append(_progress_event_to_state(created))
    return created


def _signal_from_state(data: dict[str, Any]) -> LearnerSignal:
    return LearnerSignal(
        signal_id=data["signal_id"],
        learner_id=data["learner_id"],
        signal_type=LearnerSignalType(data["signal_type"]),
        value=data["value"],
        notes=data.get("notes"),
        created_at=_parse_datetime(data["created_at"]),
    )


def _signal_to_state(signal: LearnerSignal) -> dict[str, Any]:
    return {
        "signal_id": signal.signal_id,
        "learner_id": signal.learner_id,
        "signal_type": signal.signal_type.value,
        "value": signal.value,
        "notes": signal.notes,
        "created_at": _format_datetime(signal.created_at),
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
