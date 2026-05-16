from __future__ import annotations

from dataclasses import dataclass

from rust_sensei.domain.enums import WorkspaceArtifactPolicy

LESSON_WORKSPACE_ROOT = "rust-sensei-lessons"
LESSON_SOURCE_RELATIVE_PATH = "src/main.rs"
LESSON_REPORT_FILE_NAME = "report.md"


@dataclass(frozen=True)
class AssignmentWorkspaceSuggestion:
    assignment_id: str
    workspace_dir: str
    package_root: str | None
    lesson_file_path: str | None
    report_file_path: str
    open_path: str
    create_cargo_package: bool


def build_workspace_suggestion(
    assignment_id: str,
    policy: str | WorkspaceArtifactPolicy,
) -> AssignmentWorkspaceSuggestion:
    try:
        artifact_policy = WorkspaceArtifactPolicy(policy)
    except ValueError as exc:
        raise ValueError(f"Unknown workspace artifact policy: {policy}") from exc

    workspace_dir = f"{LESSON_WORKSPACE_ROOT}/{assignment_id}"
    report_file_path = f"{workspace_dir}/{LESSON_REPORT_FILE_NAME}"

    if artifact_policy is WorkspaceArtifactPolicy.MANUAL_CARGO_PROJECT:
        return AssignmentWorkspaceSuggestion(
            assignment_id=assignment_id,
            workspace_dir=workspace_dir,
            package_root=None,
            lesson_file_path=None,
            report_file_path=report_file_path,
            open_path=workspace_dir,
            create_cargo_package=False,
        )

    lesson_file_path = f"{workspace_dir}/{LESSON_SOURCE_RELATIVE_PATH}"
    return AssignmentWorkspaceSuggestion(
        assignment_id=assignment_id,
        workspace_dir=workspace_dir,
        package_root=workspace_dir,
        lesson_file_path=lesson_file_path,
        report_file_path=report_file_path,
        open_path=lesson_file_path,
        create_cargo_package=True,
    )
