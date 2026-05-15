from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from rust_sensei.constants import (
    MCP_CURRICULUM_CONCEPTS_RESOURCE_URI,
    MCP_PROFILE_ACTIVE_RESOURCE_URI,
    MCP_PROGRESS_SUMMARY_RESOURCE_URI,
)
from rust_sensei.factory import ServiceFactory
from rust_sensei.mcp_server import register_handlers
from tests.constants import HELLO_RUST_CODE, TEST_CURRICULUM_VERSION

Handler = TypeVar("Handler", bound=Callable[..., Any])


def test_register_handlers_exposes_expected_mcp_surface(tmp_path):
    mcp = _FakeMCP()

    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))

    assert sorted(mcp.tools) == [
        "assess_attempt",
        "get_learner_profile",
        "get_next_lesson",
        "get_progress_summary",
        "get_setup_status",
        "start_session",
        "submit_attempt",
        "update_learner_signal",
    ]
    assert sorted(mcp.resources) == [
        MCP_CURRICULUM_CONCEPTS_RESOURCE_URI,
        MCP_PROFILE_ACTIVE_RESOURCE_URI,
        MCP_PROGRESS_SUMMARY_RESOURCE_URI,
    ]
    assert sorted(mcp.prompts) == ["rust_sensei_tutor"]


def test_registered_tools_validate_payload_and_return_json_payloads(tmp_path):
    mcp = _FakeMCP()
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))

    response = mcp.tools["start_session"]({"initial_rust_level": "new"})

    assert response["learner_id"] == "local-default"
    assert response["placement_required"] is False
    assert response["profile"]["rust_level_initial"] == "new"


def test_registered_tools_route_successful_lesson_flow(tmp_path):
    mcp = _FakeMCP()
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))
    mcp.tools["start_session"]({"initial_rust_level": "new"})

    profile = mcp.tools["get_learner_profile"]({})
    lesson = mcp.tools["get_next_lesson"]({})
    progress = mcp.tools["get_progress_summary"]({})
    setup = mcp.tools["get_setup_status"]({})
    signal = mcp.tools["update_learner_signal"](
        {
            "signal_type": "confidence",
            "value": 0.4,
            "notes": "Still learning cargo basics.",
        }
    )
    attempt = mcp.tools["submit_attempt"](
        {
            "assignment_id": lesson["assignment"]["assignment_id"],
            "code": HELLO_RUST_CODE,
            "compiler_output": "Finished dev profile",
        }
    )
    assessment = mcp.tools["assess_attempt"](
        {
            "attempt_id": attempt["attempt_id"],
        }
    )

    assert profile["profile"]["learner_id"] == "local-default"
    assert lesson["assignment"]["assignment_id"] == "assign_000001"
    assert progress["learner_id"] == "local-default"
    assert "ready" in setup
    assert signal["recorded"] is True
    assert attempt["attempt_id"] == "attempt_000001"
    assert assessment["assessment"]["attempt_id"] == "attempt_000001"


def test_registered_tools_return_structured_validation_errors(tmp_path):
    mcp = _FakeMCP()
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))

    response = mcp.tools["start_session"](
        {
            "initial_rust_level": "new",
            "unexpected_field": True,
        }
    )

    assert response["error"]["error_code"] == "validation_error"
    assert response["error"]["retryable"] is False


def test_registered_resources_return_structured_service_errors(tmp_path):
    mcp = _FakeMCP()
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))

    response = mcp.resources[MCP_PROFILE_ACTIVE_RESOURCE_URI]()

    assert response["error"]["error_code"] == "not_found"
    assert response["error"]["retryable"] is False


def test_registered_resources_return_json_payloads(tmp_path):
    mcp = _FakeMCP()
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))
    mcp.tools["start_session"]({"initial_rust_level": "new"})

    profile = mcp.resources[MCP_PROFILE_ACTIVE_RESOURCE_URI]()
    progress = mcp.resources[MCP_PROGRESS_SUMMARY_RESOURCE_URI]()
    curriculum = mcp.resources[MCP_CURRICULUM_CONCEPTS_RESOURCE_URI]()

    assert profile["profile"]["learner_id"] == "local-default"
    assert progress["learner_id"] == "local-default"
    assert curriculum["curriculum_version"] == TEST_CURRICULUM_VERSION
    assert len(curriculum["concepts"]) > 0


def test_registered_prompt_returns_tutor_prompt(tmp_path):
    mcp = _FakeMCP()
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))

    prompt = mcp.prompts["rust_sensei_tutor"]()

    assert "Rust Sensei" in prompt


class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.resources: dict[str, Callable[[], dict[str, Any]]] = {}
        self.prompts: dict[str, Callable[[], str]] = {}

    def tool(self) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.tools[handler.__name__] = handler
            return handler

        return decorator

    def resource(self, uri: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.resources[uri] = handler
            return handler

        return decorator

    def prompt(self) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.prompts[handler.__name__] = handler
            return handler

        return decorator
