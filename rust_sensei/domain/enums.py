from enum import Enum


class RustLevel(str, Enum):
    NEW = "new"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    PROFICIENT = "proficient"
    EXPERT = "expert"


class SetupCheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
