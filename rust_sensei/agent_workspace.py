from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rust_sensei.dto.lesson import AssignmentWorkspaceSuggestionDTO

DEFAULT_MAIN_RS = """fn main() {
    // Start your Rust Sensei lesson here.
}
"""


@dataclass(frozen=True)
class PreparedLessonWorkspace:
    workspace_dir: Path
    package_root: Path | None
    lesson_file_path: Path | None
    report_file_path: Path
    open_path: Path
    created_paths: tuple[Path, ...]
    reused_paths: tuple[Path, ...]


def prepare_lesson_workspace(
    suggestion: AssignmentWorkspaceSuggestionDTO,
    workspace_root: Path,
) -> PreparedLessonWorkspace:
    root = workspace_root.expanduser()
    workspace_dir = _resolve_under_root(root, suggestion.workspace_dir)
    report_file_path = _resolve_under_root(root, suggestion.report_file_path)
    open_path = _resolve_under_root(root, suggestion.open_path)
    package_root = (
        None
        if suggestion.package_root is None
        else _resolve_under_root(root, suggestion.package_root)
    )
    lesson_file_path = (
        None
        if suggestion.lesson_file_path is None
        else _resolve_under_root(root, suggestion.lesson_file_path)
    )

    _require_self_or_child(workspace_dir, report_file_path, "report_file_path")
    _require_self_or_child(workspace_dir, open_path, "open_path")

    created: list[Path] = []
    reused: list[Path] = []
    _ensure_dir(workspace_dir, created, reused)

    if suggestion.create_cargo_package:
        if package_root is None or lesson_file_path is None:
            raise ValueError(
                "package_root and lesson_file_path are required for generated Cargo packages"
            )
        if package_root != workspace_dir:
            raise ValueError(
                "package_root must match workspace_dir for generated Cargo packages"
            )
        _require_self_or_child(package_root, lesson_file_path, "lesson_file_path")
        _ensure_cargo_binary_package(
            package_root=package_root,
            lesson_file_path=lesson_file_path,
            assignment_id=suggestion.assignment_id,
            created=created,
            reused=reused,
        )
    elif package_root is not None or lesson_file_path is not None:
        raise ValueError(
            "manual project suggestions must not include generated package paths"
        )

    return PreparedLessonWorkspace(
        workspace_dir=workspace_dir,
        package_root=package_root,
        lesson_file_path=lesson_file_path,
        report_file_path=report_file_path,
        open_path=open_path,
        created_paths=tuple(created),
        reused_paths=tuple(reused),
    )


def _ensure_cargo_binary_package(
    package_root: Path,
    lesson_file_path: Path,
    assignment_id: str,
    created: list[Path],
    reused: list[Path],
) -> None:
    _ensure_dir(lesson_file_path.parent, created, reused)
    _ensure_file(
        package_root / "Cargo.toml",
        _cargo_toml(assignment_id),
        created,
        reused,
    )
    _ensure_file(lesson_file_path, DEFAULT_MAIN_RS, created, reused)


def _ensure_dir(path: Path, created: list[Path], reused: list[Path]) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Workspace path exists and is not a directory: {path}")
        reused.append(path)
        return

    path.mkdir(parents=True, exist_ok=False)
    created.append(path)


def _ensure_file(
    path: Path,
    content: str,
    created: list[Path],
    reused: list[Path],
) -> None:
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Workspace path exists and is not a file: {path}")
        reused.append(path)
        return

    path.write_text(content, encoding="utf-8")
    created.append(path)


def _require_self_or_child(parent: Path, child: Path, label: str) -> None:
    if child != parent and parent not in child.parents:
        raise ValueError(f"{label} must be inside the assignment workspace: {child}")


def _cargo_toml(assignment_id: str) -> str:
    package_name = assignment_id.replace("_", "-")
    return (
        "[package]\n"
        f'name = "rust-sensei-{package_name}"\n'
        'version = "0.1.0"\n'
        'edition = "2021"\n'
        "\n"
        "[dependencies]\n"
    )


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError(
            f"Workspace suggestions must use relative paths: {relative_path}"
        )

    resolved_root = root.resolve(strict=False)
    resolved_candidate = (resolved_root / candidate).resolve(strict=False)
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError(
            f"Workspace suggestion escapes the workspace root: {relative_path}"
        )
    return resolved_candidate
