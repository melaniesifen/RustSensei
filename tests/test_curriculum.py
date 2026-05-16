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
                    "default_difficulty": "guided",
                    "learner_command": "cargo run",
                    "rubric_ids": ["rust_correctness"],
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
