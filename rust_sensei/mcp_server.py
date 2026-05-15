from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from rust_sensei.dto.assessment import AssessAttemptRequest
from rust_sensei.dto.attempt import SubmitAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.progress import GetProgressSummaryRequest
from rust_sensei.dto.session import (
    GetLearnerProfileRequest,
    StartSessionRequest,
    UpdateLearnerSignalRequest,
)
from rust_sensei.dto.setup import GetSetupStatusRequest
from rust_sensei.errors import RustSenseiError
from rust_sensei.factory import ServiceFactory
from rust_sensei.logging_config import log_boundary_exception
from rust_sensei.prompts.tutor_prompts import TUTOR_PROMPT

LOGGER = logging.getLogger(__name__)


def run(state_dir: Path | None = None) -> None:
    from mcp.server.fastmcp import FastMCP

    services = ServiceFactory(state_dir=state_dir)
    session_service = services.session_service()
    lesson_service = services.lesson_service()
    assessment_service = services.assessment_service()
    progress_service = services.progress_service()
    setup_service = services.setup_service()
    mcp = FastMCP("rust-sensei")

    @mcp.tool()
    def start_session(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = StartSessionRequest.model_validate(payload)
            return session_service.start_session(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def get_learner_profile(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = GetLearnerProfileRequest.model_validate(payload)
            return session_service.get_learner_profile(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def get_next_lesson(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = GetNextLessonRequest.model_validate(payload)
            return lesson_service.get_next_lesson(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def submit_attempt(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = SubmitAttemptRequest.model_validate(payload)
            return assessment_service.submit_attempt(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def assess_attempt(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = AssessAttemptRequest.model_validate(payload)
            return assessment_service.assess_attempt(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def get_progress_summary(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = GetProgressSummaryRequest.model_validate(payload)
            return progress_service.get_progress_summary(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def update_learner_signal(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = UpdateLearnerSignalRequest.model_validate(payload)
            return session_service.update_learner_signal(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.tool()
    def get_setup_status(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = GetSetupStatusRequest.model_validate(payload)
            return setup_service.get_setup_status(request).model_dump(mode="json")
        except (RustSenseiError, PydanticValidationError) as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.resource("rust-sensei://profile/active")
    def active_profile() -> dict[str, Any]:
        try:
            return session_service.get_active_profile().model_dump(mode="json")
        except RustSenseiError as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.resource("rust-sensei://progress/summary")
    def progress_summary() -> dict[str, Any]:
        try:
            return progress_service.get_active_progress_summary().model_dump(mode="json")
        except RustSenseiError as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.resource("rust-sensei://curriculum/concepts")
    def curriculum_concepts() -> dict[str, Any]:
        try:
            return lesson_service.list_curriculum_concepts().model_dump(mode="json")
        except RustSenseiError as exc:
            log_boundary_exception(LOGGER, exc)
            return _error_payload(exc)

    @mcp.prompt()
    def rust_sensei_tutor() -> str:
        return TUTOR_PROMPT

    mcp.run()


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, RustSenseiError):
        return {"error": exc.envelope.to_dict()}

    return {
        "error": {
            "error_code": "validation_error",
            "message": str(exc),
            "details": {},
            "retryable": False,
        }
    }
