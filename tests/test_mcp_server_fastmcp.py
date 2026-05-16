from __future__ import annotations

import asyncio

import pytest

from rust_sensei.factory import ServiceFactory
from rust_sensei.mcp_server import register_handlers

pytest.importorskip("mcp.server.fastmcp")

from mcp.server.fastmcp import FastMCP


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


def _call_tool(tmp_path, name: str, arguments: dict) -> dict:
    async def run() -> dict:
        mcp = FastMCP("rust-sensei-test")
        register_handlers(mcp, ServiceFactory(state_dir=tmp_path))
        _, structured = await mcp.call_tool(name, arguments)
        return structured

    return asyncio.run(run())
