from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from rust_sensei.constants import (
    ACTIVE_LEARNER_ID,
    MCP_CURRICULUM_CONCEPTS_RESOURCE_URI,
    MCP_PROFILE_ACTIVE_RESOURCE_URI,
    MCP_PROGRESS_SUMMARY_RESOURCE_URI,
    MCP_SERVER_NAME,
)
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
from rust_sensei.errors import RustSenseiError, boundary_error_payload
from rust_sensei.factory import ServiceFactory
from rust_sensei.logging_config import log_boundary_exception
from rust_sensei.prompts.tutor_prompts import (
    ATTEMPT_REVIEW_PROMPT,
    STUCK_COACHING_PROMPT,
    TUTOR_PROMPT,
)

LOGGER = logging.getLogger(__name__)
Handler = TypeVar("Handler", bound=Callable[..., Any])
RequestModel = TypeVar("RequestModel", bound=BaseModel)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class MCPRegistrar(Protocol):
    def tool(self) -> Callable[[Handler], Handler]:
        ...

    def resource(self, uri: str) -> Callable[[Handler], Handler]:
        ...

    def prompt(self) -> Callable[[Handler], Handler]:
        ...


def run(state_dir: Path | None = None) -> None:
    from mcp.server.fastmcp import FastMCP

    services = ServiceFactory(state_dir=state_dir)
    mcp = FastMCP(MCP_SERVER_NAME)
    register_handlers(mcp, services)
    mcp.run()


def register_handlers(mcp: MCPRegistrar, services: ServiceFactory) -> None:
    session_service = services.session_service()
    lesson_service = services.lesson_service()
    assessment_service = services.assessment_service()
    progress_service = services.progress_service()
    setup_service = services.setup_service()

    @mcp.tool()
    def start_session(
        learner_id: str = ACTIVE_LEARNER_ID,
        initial_rust_level: str | None = None,
    ) -> dict[str, Any]:
        """Create or resume the active Rust Sensei learner session."""
        return _execute_tool(
            StartSessionRequest,
            _payload_from_arguments(StartSessionRequest, locals()),
            session_service.start_session,
        )

    @mcp.tool()
    def get_learner_profile(
        learner_id: str = ACTIVE_LEARNER_ID,
    ) -> dict[str, Any]:
        """Return the active learner profile and skill model."""
        return _execute_tool(
            GetLearnerProfileRequest,
            _payload_from_arguments(GetLearnerProfileRequest, locals()),
            session_service.get_learner_profile,
        )

    @mcp.tool()
    def get_next_lesson(
        learner_id: str = ACTIVE_LEARNER_ID,
        force_new_variant: bool = False,
        abandon_active_assignment: bool = False,
        abandonment_reason: str | None = None,
    ) -> dict[str, Any]:
        """Return the next adaptive Rust lesson for the learner."""
        return _execute_tool(
            GetNextLessonRequest,
            _payload_from_arguments(GetNextLessonRequest, locals()),
            lesson_service.get_next_lesson,
        )

    @mcp.tool()
    def submit_attempt(
        assignment_id: str | None = None,
        learner_id: str = ACTIVE_LEARNER_ID,
        client_request_id: str | None = None,
        client_request_fingerprint: str | None = None,
        workspace_root: str | None = None,
        code: str | None = None,
        file_paths: list[str] | None = None,
        commands_run_by_learner: list[str] | None = None,
        verification_commands_run_by_agent: list[str] | None = None,
        compiler_output: str | None = None,
        runtime_output: str | None = None,
        test_output: str | None = None,
        command_run_metadata: list[dict[str, Any]] | None = None,
        output_truncated: bool = False,
        truncation_reason: str | None = None,
        omitted_files: list[str] | None = None,
        learner_notes: str | None = None,
        agent_notes: str | None = None,
        learner_execution_missing: bool = False,
        learner_execution_notes: str | None = None,
    ) -> dict[str, Any]:
        """Persist a learner attempt for later assessment."""
        return _execute_tool(
            SubmitAttemptRequest,
            _payload_from_arguments(SubmitAttemptRequest, locals()),
            assessment_service.submit_attempt,
        )

    @mcp.tool()
    def assess_attempt(attempt_id: str | None = None) -> dict[str, Any]:
        """Assess an attempt and update learner state."""
        return _execute_tool(
            AssessAttemptRequest,
            _payload_from_arguments(AssessAttemptRequest, locals()),
            assessment_service.assess_attempt,
        )

    @mcp.tool()
    def get_progress_summary(
        learner_id: str = ACTIVE_LEARNER_ID,
    ) -> dict[str, Any]:
        """Return the learner's progress summary."""
        return _execute_tool(
            GetProgressSummaryRequest,
            _payload_from_arguments(GetProgressSummaryRequest, locals()),
            progress_service.get_progress_summary,
        )

    @mcp.tool()
    def update_learner_signal(
        signal_type: str | None = None,
        value: str | float | bool | None = None,
        learner_id: str = ACTIVE_LEARNER_ID,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a non-code learner signal."""
        return _execute_tool(
            UpdateLearnerSignalRequest,
            _payload_from_arguments(UpdateLearnerSignalRequest, locals()),
            session_service.update_learner_signal,
        )

    @mcp.tool()
    def get_setup_status(
        learner_id: str = ACTIVE_LEARNER_ID,
    ) -> dict[str, Any]:
        """Return local setup diagnostics."""
        return _execute_tool(
            GetSetupStatusRequest,
            _payload_from_arguments(GetSetupStatusRequest, locals()),
            setup_service.get_setup_status,
        )

    @mcp.resource(MCP_PROFILE_ACTIVE_RESOURCE_URI)
    def active_profile() -> dict[str, Any]:
        try:
            return session_service.get_active_profile().model_dump(mode="json")
        except RustSenseiError as exc:
            log_boundary_exception(LOGGER, exc)
            return boundary_error_payload(exc)

    @mcp.resource(MCP_PROGRESS_SUMMARY_RESOURCE_URI)
    def progress_summary() -> dict[str, Any]:
        try:
            return progress_service.get_active_progress_summary().model_dump(mode="json")
        except RustSenseiError as exc:
            log_boundary_exception(LOGGER, exc)
            return boundary_error_payload(exc)

    @mcp.resource(MCP_CURRICULUM_CONCEPTS_RESOURCE_URI)
    def curriculum_concepts() -> dict[str, Any]:
        try:
            return lesson_service.list_curriculum_concepts().model_dump(mode="json")
        except RustSenseiError as exc:
            log_boundary_exception(LOGGER, exc)
            return boundary_error_payload(exc)

    @mcp.prompt()
    def rust_sensei_tutor() -> str:
        return TUTOR_PROMPT

    @mcp.prompt()
    def rust_sensei_attempt_review() -> str:
        return ATTEMPT_REVIEW_PROMPT

    @mcp.prompt()
    def rust_sensei_stuck_coaching() -> str:
        return STUCK_COACHING_PROMPT


def _execute_tool(
    request_model: type[RequestModel],
    payload: dict[str, Any],
    handler: Callable[[RequestModel], ResponseModel],
) -> dict[str, Any]:
    try:
        request = request_model.model_validate(payload)
        return handler(request).model_dump(mode="json")
    except (RustSenseiError, PydanticValidationError) as exc:
        log_boundary_exception(LOGGER, exc)
        return boundary_error_payload(exc)


def _payload_from_arguments(
    request_model: type[BaseModel],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in arguments.items()
        if key in request_model.model_fields and value is not None
    }
