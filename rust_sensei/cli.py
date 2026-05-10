from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from rust_sensei.dto.setup import GetSetupStatusRequest
from rust_sensei.errors import RustSenseiError
from rust_sensei.factory import ServiceFactory
from rust_sensei.logging_config import log_boundary_exception

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "mcp":
        from rust_sensei.mcp_server import run

        run(state_dir=args.state_dir)
        return 0

    if args.command == "setup-status":
        return _print_setup_status(args.state_dir)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rust-sensei")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Directory for local Rust Sensei state.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("mcp", help="Run the MCP server over stdio.")
    subparsers.add_parser("setup-status", help="Print setup diagnostics as JSON.")
    return parser


def _print_setup_status(state_dir: Path | None) -> int:
    try:
        response = ServiceFactory(state_dir=state_dir).setup_service().get_setup_status(
            GetSetupStatusRequest()
        )
    except (RustSenseiError, PydanticValidationError) as exc:
        log_boundary_exception(LOGGER, exc)
        print(json.dumps(_error_payload(exc), indent=2, sort_keys=True))
        return 1

    print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if response.ready else 1


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
