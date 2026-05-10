import pytest

from rust_sensei.domain.curriculum import Curriculum


def test_default_variant_matches_default_difficulty():
    curriculum = Curriculum.from_dict(
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
