from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from rust_sensei.domain.enums import RustLevel
from rust_sensei.dto.assessment import AssessAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.factory import ServiceFactory
from tests.constants import HELLO_RUST_CODE


def test_codex_agent_workflow_example_runs_lesson_helper_flow(tmp_path):
    example = _load_codex_agent_workflow_example()
    services = ServiceFactory(state_dir=tmp_path / "state")
    services.session_service().start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )
    lesson = services.lesson_service().get_next_lesson(GetNextLessonRequest())

    prepared = example.prepare_lesson_for_codex(
        lesson,
        tmp_path / "learner-workspace",
    )
    assert prepared.workspace.lesson_file_path is not None
    prepared.workspace.lesson_file_path.write_text(HELLO_RUST_CODE, encoding="utf-8")

    evidence = example.CodexCommandEvidence(
        commands_run_by_learner=("cargo run",),
        verification_commands_run_by_agent=("cargo check",),
        compiler_output="Finished dev profile",
    )
    attempt_request = example.build_codex_attempt_request(
        prepared,
        evidence,
        learner_notes="The learner ran the lesson command first.",
        agent_notes="Codex verified with cargo check.",
    )
    submitted = services.assessment_service().submit_attempt(attempt_request)
    assessed = services.assessment_service().assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )
    report_path = example.write_codex_assessment_report(
        prepared,
        assessed.assessment,
        attempt=attempt_request,
        agent_guidance="Agent guidance: keep practicing small variations.",
    )

    assert attempt_request.workspace_root is None
    assert attempt_request.file_paths == [
        f"rust-sensei-lessons/{prepared.assignment.assignment_id}/src/main.rs"
    ]
    assert report_path == prepared.workspace.report_file_path
    assert submitted.attempt_id in report_path.read_text(encoding="utf-8")


def test_codex_agent_workflow_example_opens_editor_only_when_requested(
    monkeypatch,
    tmp_path,
):
    example = _load_codex_agent_workflow_example()
    services = ServiceFactory(state_dir=tmp_path / "state")
    services.session_service().start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )
    lesson = services.lesson_service().get_next_lesson(GetNextLessonRequest())
    opened = []

    def fake_open_with_vscode(path, *, command):
        opened.append((path, command))

    monkeypatch.setattr(example, "open_with_vscode", fake_open_with_vscode)

    prepared = example.prepare_lesson_for_codex(
        lesson,
        tmp_path / "learner-workspace",
        open_editor=True,
        code_command="codium",
    )

    assert opened == [(prepared.workspace.open_path, "codium")]


def _load_codex_agent_workflow_example():
    example_path = Path(__file__).parents[1] / "examples" / "codex_agent_workflow.py"
    spec = importlib.util.spec_from_file_location(
        "codex_agent_workflow_example",
        example_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
