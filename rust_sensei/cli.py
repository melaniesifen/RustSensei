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
DOCTOR_TITLE = "Rust Sensei Doctor"
DOCTOR_READY_STATUS = "ready"
DOCTOR_NOT_READY_STATUS = "not ready"
DOCTOR_ERROR_STATUS = "error"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "mcp":
        from rust_sensei.mcp_server import run

        run(state_dir=args.state_dir)
        return 0

    if args.command == "setup-status":
        return _print_setup_status(args.state_dir)

    if args.command == "doctor":
        return _print_doctor(args.state_dir, json_output=args.json)

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
    doctor_parser = subparsers.add_parser("doctor", help="Run local setup diagnostics.")
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print diagnostics as JSON.",
    )
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


def _print_doctor(state_dir: Path | None, json_output: bool = False) -> int:
    try:
        response = ServiceFactory(state_dir=state_dir).setup_service().get_setup_status(
            GetSetupStatusRequest()
        )
    except (RustSenseiError, PydanticValidationError) as exc:
        log_boundary_exception(LOGGER, exc)
        payload = _error_payload(exc)
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(DOCTOR_TITLE)
            print(f"Status: {DOCTOR_ERROR_STATUS}")
            print(f"{DOCTOR_ERROR_STATUS}: {payload['error']['message']}")
        return 1

    if json_output:
        print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        print(DOCTOR_TITLE)
        status = DOCTOR_READY_STATUS if response.ready else DOCTOR_NOT_READY_STATUS
        print(f"Status: {status}")
        for check in response.checks:
            print(f"[{check.status.value}] {check.check_id}: {check.message}")

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
