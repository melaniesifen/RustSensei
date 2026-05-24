from copy import deepcopy

import pytest

from rust_sensei.domain.curriculum import Curriculum


def test_default_variant_matches_default_difficulty():
    curriculum = Curriculum.from_dict(
        {
            "curriculum_version": "test",
            "branch_fallbacks": {"global_branch": ["variables"]},
            "concepts": [
                {
                    "concept_id": "variables",
                    "title": "Variables",
                    "order": 1,
                    "competency_goals": ["Declare variables"],
                    "baseline_task": "Print a variable",
                    "stretch_signals": ["Uses clear names"],
                    "struggle_signals": ["Cannot compile a let binding"],
                    "default_difficulty": "guided",
                    "learner_command": "cargo run",
                    "rubric_ids": ["rust_correctness"],
                    "completion_thresholds": {"rust_correctness": 0.7},
                    "branch_targets": {"local_branch": ["variables"]},
                    "variants": [
                        {
                            "variant_id": "intro_001",
                            "difficulty": "intro",
                            "prompt": "Intro",
                            "success_criteria": ["Compiles"],
                        },
                        {
                            "variant_id": "guided_001",
                            "difficulty": "guided",
                            "prompt": "Guided",
                            "success_criteria": ["Compiles"],
                        },
                    ],
                }
            ],
        }
    )

    variant = curriculum.concepts["variables"].default_variant()

    assert variant.variant_id == "guided_001"
    assert curriculum.branch_fallbacks == {"global_branch": ["variables"]}
    assert curriculum.concepts["variables"].branch_targets == {
        "local_branch": ["variables"]
    }
    assert curriculum.concepts["variables"].prerequisites == []
    assert curriculum.concepts["variables"].competency_goals == [
        "Declare variables"
    ]
    assert curriculum.concepts["variables"].baseline_task == "Print a variable"
    assert curriculum.concepts["variables"].stretch_signals == [
        "Uses clear names"
    ]
    assert curriculum.concepts["variables"].struggle_signals == [
        "Cannot compile a let binding"
    ]
    assert curriculum.concepts["variables"].next_concepts == []
    assert curriculum.concepts["variables"].completion_thresholds == {
        "rust_correctness": 0.7
    }
    assert (
        curriculum.concepts["variables"].default_variant().workspace_artifact_policy
        == "cargo_binary_package"
    )


def test_curriculum_rejects_missing_default_difficulty_variant():
    with pytest.raises(ValueError):
        Curriculum.from_dict(
            {
                "curriculum_version": "test",
                "concepts": [
                    {
                        "concept_id": "variables",
                        "title": "Variables",
                        "order": 1,
                        "default_difficulty": "guided",
                        "learner_command": "cargo run",
                        "rubric_ids": ["rust_correctness"],
                        "variants": [
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "prompt": "Intro",
                                "success_criteria": ["Compiles"],
                            }
                        ],
                    }
                ],
            }
        )


def test_curriculum_rejects_duplicate_variant_ids():
    with pytest.raises(ValueError):
        Curriculum.from_dict(
            {
                "curriculum_version": "test",
                "concepts": [
                    {
                        "concept_id": "variables",
                        "title": "Variables",
                        "order": 1,
                        "default_difficulty": "intro",
                        "learner_command": "cargo run",
                        "rubric_ids": ["rust_correctness"],
                        "variants": [
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "prompt": "Intro",
                                "success_criteria": ["Compiles"],
                            },
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "prompt": "Other",
                                "success_criteria": ["Compiles"],
                            },
                        ],
                    }
                ],
            }
        )


def test_curriculum_rejects_unknown_branch_target():
    with pytest.raises(ValueError):
        Curriculum.from_dict(
            {
                "curriculum_version": "test",
                "concepts": [
                    {
                        "concept_id": "variables",
                        "title": "Variables",
                        "order": 1,
                        "default_difficulty": "intro",
                        "learner_command": "cargo run",
                        "rubric_ids": ["rust_correctness"],
                        "branch_targets": {"missing_branch": ["missing"]},
                        "variants": [
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "prompt": "Intro",
                                "success_criteria": ["Compiles"],
                            }
                        ],
                    }
                ],
            }
        )


def test_curriculum_rejects_unknown_workspace_artifact_policy():
    with pytest.raises(ValueError):
        Curriculum.from_dict(
            {
                "curriculum_version": "test",
                "concepts": [
                    {
                        "concept_id": "variables",
                        "title": "Variables",
                        "order": 1,
                        "default_difficulty": "intro",
                        "learner_command": "cargo run",
                        "rubric_ids": ["rust_correctness"],
                        "variants": [
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "workspace_artifact_policy": "unknown",
                                "prompt": "Intro",
                                "success_criteria": ["Compiles"],
                            }
                        ],
                    }
                ],
            }
        )


def test_curriculum_rejects_blank_required_text_fields():
    data = _valid_curriculum()
    data["concepts"][0]["variants"][0]["prompt"] = "   "

    with pytest.raises(ValueError, match="prompt"):
        Curriculum.from_dict(data)


def test_curriculum_rejects_non_list_concepts():
    data = _valid_curriculum()
    data["concepts"] = {"concept_id": "variables"}

    with pytest.raises(ValueError, match="concepts must be a list"):
        Curriculum.from_dict(data)


def test_curriculum_rejects_empty_concept_list():
    data = _valid_curriculum()
    data["concepts"] = []

    with pytest.raises(ValueError, match="at least 1 concept"):
        Curriculum.from_dict(data)


def test_curriculum_rejects_duplicate_concept_order_values():
    data = _valid_curriculum()
    other = deepcopy(data["concepts"][0])
    other["concept_id"] = "ownership"
    other["title"] = "Ownership"
    other["variants"][0]["variant_id"] = "intro_002"
    data["concepts"].append(other)

    with pytest.raises(ValueError, match="Duplicate concept order"):
        Curriculum.from_dict(data)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("concepts", 0, "default_difficulty"), "unknown"),
        (("concepts", 0, "variants", 0, "difficulty"), "unknown"),
    ],
)
def test_curriculum_rejects_unknown_difficulty_values(field_path, value):
    data = _valid_curriculum()
    target = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(ValueError, match="invalid .*difficulty"):
        Curriculum.from_dict(data)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("concepts", 0, "rubric_ids"), []),
        (("concepts", 0, "variants", 0, "success_criteria"), []),
        (("concepts", 0, "variants", 0, "hints"), [""]),
    ],
)
def test_curriculum_rejects_invalid_string_lists(field_path, value):
    data = _valid_curriculum()
    target = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(ValueError):
        Curriculum.from_dict(data)


@pytest.mark.parametrize(
    "branch_targets",
    [
        {"": ["variables"]},
        {"branch": "variables"},
        {"branch": []},
        {"branch": [""]},
    ],
)
def test_curriculum_rejects_malformed_branch_targets(branch_targets):
    data = _valid_curriculum()
    data["concepts"][0]["branch_targets"] = branch_targets

    with pytest.raises(ValueError):
        Curriculum.from_dict(data)


@pytest.mark.parametrize("field_name", ["prerequisites", "next_concepts"])
def test_curriculum_rejects_unknown_graph_references(field_name):
    data = _valid_curriculum()
    data["concepts"][0][field_name] = ["missing"]

    with pytest.raises(ValueError, match=field_name):
        Curriculum.from_dict(data)


@pytest.mark.parametrize(
    "completion_thresholds",
    [
        {"rust_correctness": -0.1},
        {"rust_correctness": 1.1},
        {"rust_correctness": float("nan")},
        {"rust_correctness": float("inf")},
        {"rust_correctness": "high"},
        {"unknown_rubric": 0.7},
        {"": 0.7},
    ],
)
def test_curriculum_rejects_malformed_completion_thresholds(
    completion_thresholds,
):
    data = _valid_curriculum()
    data["concepts"][0]["completion_thresholds"] = completion_thresholds

    with pytest.raises(ValueError):
        Curriculum.from_dict(data)


def test_curriculum_rejects_invalid_lesson_command_shape():
    data = _valid_curriculum()
    data["concepts"][0]["variants"][0]["lesson_commands"][0]["required"] = "true"

    with pytest.raises(ValueError, match="required"):
        Curriculum.from_dict(data)


def _valid_curriculum():
    return {
        "curriculum_version": "test",
        "branch_fallbacks": {"global_branch": ["variables"]},
        "concepts": [
            {
                "concept_id": "variables",
                "title": "Variables",
                "order": 1,
                "prerequisites": [],
                "default_difficulty": "intro",
                "competency_goals": ["Declare variables"],
                "baseline_task": "Print a variable",
                "learner_command": "cargo run",
                "stretch_signals": ["Uses clear names"],
                "struggle_signals": ["Cannot compile a let binding"],
                "rubric_ids": ["rust_correctness"],
                "next_concepts": [],
                "branch_targets": {"local_branch": ["variables"]},
                "completion_thresholds": {"rust_correctness": 0.7},
                "variants": [
                    {
                        "variant_id": "intro_001",
                        "difficulty": "intro",
                        "prompt": "Intro",
                        "success_criteria": ["Compiles"],
                        "hints": ["Run cargo run"],
                        "lesson_commands": [
                            {
                                "command": "cargo run",
                                "purpose": "Run the program",
                                "risk_level": "low",
                                "required": True,
                                "allowed_for_agent_verification": True,
                            }
                        ],
                    }
                ],
            }
        ],
    }
