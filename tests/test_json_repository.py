import json

import pytest

from rust_sensei.domain.enums import RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.skill import SkillModel
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import StorageError
from rust_sensei.repositories.json_state import JsonStateStore
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.session_service import SessionService


def test_json_repository_creates_expected_state_shape(tmp_path):
    service = SessionService(
        learner_repository=JsonRepositoryFactory(tmp_path).learner_repository(),
        now=_fixed_now,
    )

    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert state["state_revision"] == 2
    assert state["active_learner_id"] == "local-default"
    assert "local-default" in state["learners"]
    assert state["lesson_assignments"] == []
    assert state["attempts"] == []
    assert state["assessments"] == []
    assert state["progress_events"] == []
    assert state["signals"] == []


def test_json_state_rejects_invalid_json(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{", encoding="utf-8")

    with pytest.raises(StorageError):
        JsonStateStore(state_path).read()


def test_json_state_rejects_unsupported_schema_version(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 999}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        JsonStateStore(state_path).read()


def test_create_profile_if_absent_keeps_original_profile(tmp_path):
    repository = JsonRepositoryFactory(tmp_path).learner_repository()
    first = _profile(RustLevel.NEW)
    second = _profile(RustLevel.EXPERT)

    created = repository.create_profile_if_absent(first)
    existing = repository.create_profile_if_absent(second)

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert created.rust_level_initial == RustLevel.NEW
    assert existing.rust_level_initial == RustLevel.NEW
    assert state["learners"]["local-default"]["rust_level_initial"] == "new"
    assert state["state_revision"] == 2


def _fixed_now():
    from datetime import datetime, timezone

    return datetime(2026, 5, 10, tzinfo=timezone.utc)


def _profile(level):
    return LearnerProfile(
        learner_id="local-default",
        rust_level_initial=level,
        active_concept_id=None,
        skill_model=SkillModel(),
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
