from __future__ import annotations

import asyncio
import json

import pytest

from rust_sensei.constants import (
    MCP_CURRICULUM_CONCEPTS_RESOURCE_URI,
    MCP_PROFILE_ACTIVE_RESOURCE_URI,
    MCP_PROGRESS_SUMMARY_RESOURCE_URI,
)
from rust_sensei.factory import ServiceFactory
from rust_sensei.mcp_server import register_handlers
from tests.constants import TEST_CURRICULUM_VERSION

pytest.importorskip("mcp.server.fastmcp")

from mcp.server.fastmcp import FastMCP


def test_fastmcp_registers_tools_resources_and_prompts(tmp_path):
    result = _run_fastmcp(tmp_path, _registered_surface)

    assert result["tools"] == [
        "assess_attempt",
        "get_learner_profile",
        "get_next_lesson",
        "get_progress_summary",
        "get_setup_status",
        "start_session",
        "submit_attempt",
        "update_learner_signal",
    ]
    assert result["resources"] == [
        MCP_CURRICULUM_CONCEPTS_RESOURCE_URI,
        MCP_PROFILE_ACTIVE_RESOURCE_URI,
        MCP_PROGRESS_SUMMARY_RESOURCE_URI,
    ]
    assert result["prompts"] == [
        "rust_sensei_attempt_review",
        "rust_sensei_stuck_coaching",
        "rust_sensei_tutor",
    ]


def test_fastmcp_tool_schemas_use_direct_parameters(tmp_path):
    schemas = _run_fastmcp(tmp_path, _tool_input_schemas)

    assert "payload" not in schemas["start_session"]["properties"]
    assert "initial_rust_level" in schemas["start_session"]["properties"]
    assert "payload" not in schemas["submit_attempt"]["properties"]
    assert "assignment_id" in schemas["submit_attempt"]["properties"]


def test_fastmcp_invalid_enum_returns_project_error_envelope(tmp_path):
    response = _call_tool(
        tmp_path,
        "start_session",
        {"initial_rust_level": "not-a-level"},
    )

    assert response["error"]["error_code"] == "validation_error"
    assert response["error"]["retryable"] is False


def test_fastmcp_missing_required_field_returns_project_error_envelope(tmp_path):
    response = _call_tool(tmp_path, "submit_attempt", {})

    assert response["error"]["error_code"] == "validation_error"
    assert response["error"]["retryable"] is False


def test_fastmcp_successful_tool_flow_returns_structured_payloads(tmp_path):
    result = _run_fastmcp(tmp_path, _successful_tool_flow)

    assert result["session"]["profile"]["learner_id"] == "local-default"
    assert result["lesson"]["assignment"]["assignment_id"] == "assign_000001"
    assert result["attempt"]["attempt_id"] == "attempt_000001"
    assert result["assessment"]["assessment"]["attempt_id"] == "attempt_000001"
    assert result["assessment"]["assessment"]["confidence_breakdown"]["explanation"]


def test_fastmcp_resources_return_json_payloads_and_project_errors(tmp_path):
    result = _run_fastmcp(tmp_path, _resource_flow)

    assert result["missing_profile"]["error"]["error_code"] == "not_found"
    assert result["profile"]["profile"]["learner_id"] == "local-default"
    assert result["progress"]["learner_id"] == "local-default"
    assert result["curriculum"]["curriculum_version"] == TEST_CURRICULUM_VERSION
    assert result["curriculum"]["concepts"]


def test_fastmcp_prompts_return_prompt_messages(tmp_path):
    result = _run_fastmcp(tmp_path, _prompt_texts)

    assert "Rust Sensei" in result["rust_sensei_tutor"]
    assert "assess_attempt output" in result["rust_sensei_attempt_review"]
    assert "update_learner_signal" in result["rust_sensei_stuck_coaching"]


def _call_tool(tmp_path, name: str, arguments: dict) -> dict:
    return _run_fastmcp(
        tmp_path,
        lambda mcp: _call_tool_with_mcp(mcp, name, arguments),
    )


def _run_fastmcp(tmp_path, action):
    async def run():
        mcp = _mcp(tmp_path)
        return await action(mcp)

    return asyncio.run(run())


async def _registered_surface(mcp: FastMCP) -> dict[str, list[str]]:
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    prompts = await mcp.list_prompts()
    return {
        "tools": sorted(tool.name for tool in tools),
        "resources": sorted(str(resource.uri) for resource in resources),
        "prompts": sorted(prompt.name for prompt in prompts),
    }


async def _tool_input_schemas(mcp: FastMCP) -> dict[str, dict]:
    tools = await mcp.list_tools()
    return {
        tool.name: tool.inputSchema
        for tool in tools
    }


async def _call_tool_with_mcp(
    mcp: FastMCP,
    name: str,
    arguments: dict,
) -> dict:
    _, structured = await mcp.call_tool(name, arguments)
    return structured


async def _successful_tool_flow(mcp: FastMCP) -> dict[str, dict]:
    session = await _call_tool_with_mcp(
        mcp,
        "start_session",
        {"initial_rust_level": "new"},
    )
    lesson = await _call_tool_with_mcp(mcp, "get_next_lesson", {})
    attempt = await _call_tool_with_mcp(
        mcp,
        "submit_attempt",
        {
            "assignment_id": lesson["assignment"]["assignment_id"],
            "code": 'fn main() { println!("Hello, Rust!"); }',
            "compiler_output": "Finished dev profile",
        },
    )
    assessment = await _call_tool_with_mcp(
        mcp,
        "assess_attempt",
        {"attempt_id": attempt["attempt_id"]},
    )
    return {
        "session": session,
        "lesson": lesson,
        "attempt": attempt,
        "assessment": assessment,
    }


async def _resource_flow(mcp: FastMCP) -> dict[str, dict]:
    missing_profile = await _read_resource_json(mcp, MCP_PROFILE_ACTIVE_RESOURCE_URI)
    await _call_tool_with_mcp(mcp, "start_session", {"initial_rust_level": "new"})
    return {
        "missing_profile": missing_profile,
        "profile": await _read_resource_json(mcp, MCP_PROFILE_ACTIVE_RESOURCE_URI),
        "progress": await _read_resource_json(mcp, MCP_PROGRESS_SUMMARY_RESOURCE_URI),
        "curriculum": await _read_resource_json(
            mcp,
            MCP_CURRICULUM_CONCEPTS_RESOURCE_URI,
        ),
    }


async def _read_resource_json(mcp: FastMCP, uri: str) -> dict:
    contents = await mcp.read_resource(uri)
    assert len(contents) == 1
    return json.loads(contents[0].content)


async def _prompt_texts(mcp: FastMCP) -> dict[str, str]:
    names = [
        "rust_sensei_attempt_review",
        "rust_sensei_stuck_coaching",
        "rust_sensei_tutor",
    ]
    prompts = {}
    for name in names:
        result = await mcp.get_prompt(name)
        assert len(result.messages) == 1
        prompts[name] = result.messages[0].content.text
    return prompts


def _mcp(tmp_path) -> FastMCP:
    mcp = FastMCP("rust-sensei-test")
    register_handlers(mcp, ServiceFactory(state_dir=tmp_path))
    return mcp
