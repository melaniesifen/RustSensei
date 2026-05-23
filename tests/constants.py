from __future__ import annotations

from datetime import datetime, timezone

TEST_NOW = datetime(2026, 5, 10, tzinfo=timezone.utc)
TEST_LEARNER_ID = "local-default"
TEST_CURRICULUM_VERSION = "0.1.0"

CARGO_HELLO_WORLD_CONCEPT_ID = "cargo_hello_world"
VARIABLES_CONCEPT_ID = "variables_primitive_types"
OWNERSHIP_CONCEPT_ID = "ownership_borrowing_intro"
TRAITS_CONCEPT_ID = "traits_generics_testing"
ADVANCED_CONCEPT_ID = "advanced_design_review"

ASSIGNMENT_ID_1 = "assign_000001"
ASSIGNMENT_ID_2 = "assign_000002"
ATTEMPT_ID_1 = "attempt_000001"
ASSESSMENT_ID_1 = "assessment_000001"
EVENT_ID_1 = "event_000001"

HELLO_RUST_CODE = 'fn main() { println!("Hello, Rust Sensei"); }'
HELLO_RUST_OUTPUT = "Hello, Rust Sensei"
SUCCESSFUL_CARGO_OUTPUT = "Finished dev profile target(s) in 0.10s"
