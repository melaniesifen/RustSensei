from dataclasses import dataclass

from rust_sensei.domain.enums import SetupCheckStatus


@dataclass(frozen=True)
class SetupCheck:
    check_id: str
    status: SetupCheckStatus
    message: str
