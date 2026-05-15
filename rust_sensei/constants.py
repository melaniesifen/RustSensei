from typing import Final

from rust_sensei.domain.enums import RustLevel

ACTIVE_LEARNER_ID: Final = "local-default"
ALLOWED_RUST_LEVELS: Final = tuple(level.value for level in RustLevel)
SCHEMA_VERSION: Final = 1
STATE_FILE_NAME: Final = "state.json"
STATE_LOCK_FILE_NAME: Final = "state.lock"
LOG_DIR_NAME: Final = "logs"
MCP_SERVER_NAME: Final = "rust-sensei"
MCP_PROFILE_ACTIVE_RESOURCE_URI: Final = "rust-sensei://profile/active"
MCP_PROGRESS_SUMMARY_RESOURCE_URI: Final = "rust-sensei://progress/summary"
MCP_CURRICULUM_CONCEPTS_RESOURCE_URI: Final = "rust-sensei://curriculum/concepts"
