from datetime import datetime, timezone

import pytest

from rust_sensei.domain.enums import RustLevel
from rust_sensei.dto.session import GetLearnerProfileRequest, StartSessionRequest
from rust_sensei.errors import NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.session_service import SessionService


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


def _session_service(tmp_path) -> SessionService:
    repository = JsonRepositoryFactory(tmp_path).learner_repository()
    return SessionService(
        learner_repository=repository,
        now=lambda: datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
