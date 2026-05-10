from __future__ import annotations

from pydantic import Field

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.enums import SetupCheckStatus
from rust_sensei.dto.common import StrictDTO


class SetupCheckDTO(StrictDTO):
    check_id: str
    status: SetupCheckStatus
    message: str


class GetSetupStatusRequest(StrictDTO):
    learner_id: str = ACTIVE_LEARNER_ID


class GetSetupStatusResponse(StrictDTO):
    ready: bool
    checks: list[SetupCheckDTO] = Field(default_factory=list)
