from rust_sensei.prompts.tutor_prompts import TUTOR_PROMPT


def test_tutor_prompt_contains_core_agent_rules():
    assert "Call start_session before requesting a lesson" in TUTOR_PROMPT
    assert "Do not invent skill scores" in TUTOR_PROMPT
