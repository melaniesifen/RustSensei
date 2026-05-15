from rust_sensei.prompts.tutor_prompts import (
    ATTEMPT_REVIEW_PROMPT,
    STUCK_COACHING_PROMPT,
    TUTOR_PROMPT,
)


def test_tutor_prompt_contains_core_agent_rules():
    assert "Call start_session before requesting a lesson" in TUTOR_PROMPT
    assert "Do not invent skill scores" in TUTOR_PROMPT


def test_attempt_review_prompt_preserves_assessment_boundary():
    assert "assess_attempt output" in ATTEMPT_REVIEW_PROMPT
    assert "Do not overwrite, reinterpret, or invent Rust Sensei scores" in ATTEMPT_REVIEW_PROMPT


def test_stuck_coaching_prompt_records_learner_signals():
    assert "update_learner_signal" in STUCK_COACHING_PROMPT
    assert "Do not advance or branch lessons" in STUCK_COACHING_PROMPT
