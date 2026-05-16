import pytest

from rust_sensei.agent_workspace import prepare_lesson_workspace
from rust_sensei.domain.workspace import build_workspace_suggestion
from rust_sensei.dto.lesson import AssignmentWorkspaceSuggestionDTO
from tests.constants import ASSIGNMENT_ID_1


def test_prepare_lesson_workspace_creates_cargo_binary_package(tmp_path):
    suggestion = _generated_package_suggestion()

    prepared = prepare_lesson_workspace(suggestion, tmp_path)

    assert prepared.workspace_dir == tmp_path / "rust-sensei-lessons" / ASSIGNMENT_ID_1
    assert prepared.package_root == prepared.workspace_dir
    assert prepared.lesson_file_path == prepared.workspace_dir / "src" / "main.rs"
    assert prepared.open_path == prepared.lesson_file_path
    assert (prepared.workspace_dir / "Cargo.toml").read_text(
        encoding="utf-8"
    ).startswith("[package]\n")
    assert prepared.lesson_file_path is not None
    assert "fn main()" in prepared.lesson_file_path.read_text(encoding="utf-8")


def test_prepare_lesson_workspace_reuses_existing_files_without_overwriting(tmp_path):
    suggestion = _generated_package_suggestion()
    prepared = prepare_lesson_workspace(suggestion, tmp_path)
    assert prepared.lesson_file_path is not None
    prepared.lesson_file_path.write_text("fn main() {}\n", encoding="utf-8")

    reused = prepare_lesson_workspace(suggestion, tmp_path)

    assert reused.lesson_file_path.read_text(encoding="utf-8") == "fn main() {}\n"
    assert reused.created_paths == ()
    assert reused.reused_paths


def test_prepare_lesson_workspace_for_manual_cargo_project_creates_only_directory(tmp_path):
    suggestion = AssignmentWorkspaceSuggestionDTO(
        assignment_id=ASSIGNMENT_ID_1,
        workspace_dir=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        package_root=None,
        lesson_file_path=None,
        report_file_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/report.md",
        open_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        create_cargo_package=False,
    )

    prepared = prepare_lesson_workspace(suggestion, tmp_path)

    assert prepared.workspace_dir.is_dir()
    assert prepared.package_root is None
    assert prepared.lesson_file_path is None
    assert not (prepared.workspace_dir / "Cargo.toml").exists()
    assert prepared.open_path == prepared.workspace_dir


def test_prepare_lesson_workspace_rejects_absolute_suggestion_path(tmp_path):
    suggestion = _generated_package_suggestion(
        workspace_dir=str(tmp_path / "outside"),
    )

    with pytest.raises(ValueError):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_prepare_lesson_workspace_rejects_parent_escape(tmp_path):
    suggestion = _generated_package_suggestion(
        lesson_file_path="../outside/main.rs",
    )

    with pytest.raises(ValueError):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_prepare_lesson_workspace_rejects_package_root_outside_assignment_dir(tmp_path):
    suggestion = _generated_package_suggestion(
        package_root="some-existing-project",
    )

    with pytest.raises(ValueError, match="package_root must match workspace_dir"):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_prepare_lesson_workspace_rejects_lesson_file_outside_assignment_dir(tmp_path):
    suggestion = _generated_package_suggestion(
        lesson_file_path="some-existing-project/src/main.rs",
    )

    with pytest.raises(ValueError, match="lesson_file_path must be inside"):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_prepare_lesson_workspace_rejects_report_path_outside_assignment_dir(tmp_path):
    suggestion = _generated_package_suggestion(
        report_file_path="some-existing-project/report.md",
    )

    with pytest.raises(ValueError, match="report_file_path must be inside"):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_prepare_lesson_workspace_rejects_open_path_outside_assignment_dir(tmp_path):
    suggestion = _generated_package_suggestion(
        open_path="some-existing-project/src/main.rs",
    )

    with pytest.raises(ValueError, match="open_path must be inside"):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_prepare_lesson_workspace_rejects_manual_policy_with_generated_paths(tmp_path):
    suggestion = AssignmentWorkspaceSuggestionDTO(
        assignment_id=ASSIGNMENT_ID_1,
        workspace_dir=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        package_root=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        lesson_file_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/src/main.rs",
        report_file_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/report.md",
        open_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        create_cargo_package=False,
    )

    with pytest.raises(ValueError, match="manual project suggestions"):
        prepare_lesson_workspace(suggestion, tmp_path)


def test_build_workspace_suggestion_rejects_unknown_policy():
    with pytest.raises(ValueError, match="Unknown workspace artifact policy"):
        build_workspace_suggestion(ASSIGNMENT_ID_1, "unknown")


def _generated_package_suggestion(**overrides):
    data = {
        "assignment_id": ASSIGNMENT_ID_1,
        "workspace_dir": f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        "package_root": f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        "lesson_file_path": f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/src/main.rs",
        "report_file_path": f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/report.md",
        "open_path": f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/src/main.rs",
        "create_cargo_package": True,
    }
    data.update(overrides)
    return AssignmentWorkspaceSuggestionDTO.model_validate(data)
