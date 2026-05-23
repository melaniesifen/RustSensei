import json

import pytest

from rust_sensei.domain.curriculum import Curriculum
from rust_sensei.domain.enums import LearnerSignalType, RustLevel
from rust_sensei.dto.session import (
    GetLearnerProfileRequest,
    StartSessionRequest,
    UpdateLearnerSignalRequest,
)
from rust_sensei.errors import NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.session_service import SessionService
from tests.constants import (
    CARGO_HELLO_WORLD_CONCEPT_ID,
    OWNERSHIP_CONCEPT_ID,
    TEST_LEARNER_ID,
    TEST_NOW,
    TRAITS_CONCEPT_ID,
    VARIABLES_CONCEPT_ID,
)


def test_start_session_requires_placement_for_new_profile(tmp_path):
    service = _session_service(tmp_path)

    response = service.start_session(StartSessionRequest())

    assert response.placement_required is True
    assert response.allowed_placements == [
        "new",
        "beginner",
        "intermediate",
        "proficient",
        "expert",
    ]
    assert response.profile is None


def test_start_session_creates_profile_after_valid_placement(tmp_path):
    service = _session_service(tmp_path)

    response = service.start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )

    assert response.placement_required is False
    assert response.profile is not None
    assert response.profile.learner_id == "local-default"
    assert response.profile.rust_level_initial == RustLevel.BEGINNER
    assert response.profile.active_concept_id == "variables_primitive_types"


def test_start_session_records_provisional_skips_for_proficient_placement(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    service = _session_service_from_repositories(repositories)

    response = service.start_session(
        StartSessionRequest(initial_rust_level=RustLevel.PROFICIENT)
    )

    events = repositories.progress_event_repository().list_events_for_learner(
        TEST_LEARNER_ID
    )
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert response.profile is not None
    assert response.profile.active_concept_id == TRAITS_CONCEPT_ID
    assert state["state_revision"] == 2
    assert len(state["progress_events"]) == 3
    assert [event.event_type.value for event in events] == [
        "provisionally_skipped",
        "provisionally_skipped",
        "provisionally_skipped",
    ]
    assert [event.details["concept_id"] for event in reversed(events)] == [
        CARGO_HELLO_WORLD_CONCEPT_ID,
        VARIABLES_CONCEPT_ID,
        OWNERSHIP_CONCEPT_ID,
    ]
    assert all(
        event.details["placement_level"] == RustLevel.PROFICIENT.value
        and event.details["active_concept_id"] == TRAITS_CONCEPT_ID
        and event.details["reason"] == "initial_placement"
        and event.created_at == TEST_NOW
        for event in events
    )


def test_start_session_does_not_duplicate_placement_skip_events_on_reuse(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    service = _session_service_from_repositories(repositories)
    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.PROFICIENT))

    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.EXPERT))

    events = repositories.progress_event_repository().list_events_for_learner(
        TEST_LEARNER_ID
    )
    assert len(events) == 3


def test_start_session_fails_when_placement_concept_is_missing_from_curriculum(
    tmp_path,
):
    repositories = JsonRepositoryFactory(tmp_path)
    service = SessionService(
        learner_repository=repositories.learner_repository(),
        learner_signal_repository=repositories.learner_signal_repository(),
        curriculum_repository=_MissingPlacementConceptCurriculumRepository(),
        now=lambda: TEST_NOW,
    )

    with pytest.raises(ValueError, match="traits_generics_testing"):
        service.start_session(
            StartSessionRequest(initial_rust_level=RustLevel.PROFICIENT)
        )

    assert repositories.learner_repository().get_profile(TEST_LEARNER_ID) is None
    assert repositories.progress_event_repository().list_events_for_learner(
        TEST_LEARNER_ID
    ) == []


def test_start_session_reuses_existing_profile(tmp_path):
    service = _session_service(tmp_path)

    created = service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    reused = service.start_session(StartSessionRequest(initial_rust_level=RustLevel.EXPERT))

    assert created.profile is not None
    assert reused.profile is not None
    assert reused.placement_required is False
    assert reused.profile.rust_level_initial == RustLevel.NEW


def test_get_learner_profile_returns_saved_profile(tmp_path):
    service = _session_service(tmp_path)
    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.PROFICIENT))

    response = service.get_learner_profile(GetLearnerProfileRequest())

    assert response.profile.rust_level_initial == RustLevel.PROFICIENT
    assert response.profile.active_concept_id == "traits_generics_testing"
    assert response.skill_model == {
        "rust_concepts": {},
        "programming_dimensions": {},
    }


def test_get_learner_profile_requires_existing_profile(tmp_path):
    service = _session_service(tmp_path)

    with pytest.raises(NotFoundError):
        service.get_learner_profile(GetLearnerProfileRequest())


def test_unsupported_learner_id_is_rejected(tmp_path):
    service = _session_service(tmp_path)

    with pytest.raises(ValidationError):
        service.start_session(StartSessionRequest(learner_id="someone-else"))


def test_update_learner_signal_records_signal(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    service = _session_service_from_repositories(repositories)
    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    response = service.update_learner_signal(
        UpdateLearnerSignalRequest(
            signal_type=LearnerSignalType.CONFUSION,
            value=True,
            notes="Borrow checker error is confusing.",
        )
    )

    signals = repositories.learner_signal_repository().list_recent_signals(
        "local-default",
        limit=5,
    )
    assert response.signal_id == "signal_000001"
    assert response.recorded is True
    assert signals[0].signal_type == LearnerSignalType.CONFUSION
    assert signals[0].value is True
    assert signals[0].notes == "Borrow checker error is confusing."


def test_update_learner_signal_requires_existing_profile(tmp_path):
    service = _session_service(tmp_path)

    with pytest.raises(NotFoundError):
        service.update_learner_signal(
            UpdateLearnerSignalRequest(
                signal_type=LearnerSignalType.CONFIDENCE,
                value=0.25,
            )
        )


def test_update_learner_signal_rejects_blank_string_value(tmp_path):
    service = _session_service(tmp_path)
    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    with pytest.raises(ValidationError):
        service.update_learner_signal(
            UpdateLearnerSignalRequest(
                signal_type=LearnerSignalType.BLOCKER,
                value=" ",
            )
        )


def _session_service(tmp_path) -> SessionService:
    return _session_service_from_repositories(JsonRepositoryFactory(tmp_path))


def _session_service_from_repositories(
    repositories: JsonRepositoryFactory,
) -> SessionService:
    return SessionService(
        learner_repository=repositories.learner_repository(),
        learner_signal_repository=repositories.learner_signal_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        now=lambda: TEST_NOW,
    )


class _MissingPlacementConceptCurriculumRepository:
    def get_curriculum(self) -> Curriculum:
        return Curriculum(
            curriculum_version="test",
            concepts={},
        )
