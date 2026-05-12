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


class AssignmentStatus(str, Enum):
    ACTIVE = "active"
    ATTEMPTED = "attempted"
    ASSESSED = "assessed"
    ABANDONED = "abandoned"


class Difficulty(str, Enum):
    INTRO = "intro"
    GUIDED = "guided"
    STANDARD = "standard"
    CHALLENGE = "challenge"
    ADVANCED = "advanced"


class NextAction(str, Enum):
    SIMPLIFY = "simplify"
    REPEAT = "repeat"
    CONTINUE = "continue"
    ACCELERATE = "accelerate"
    BRANCH = "branch"
