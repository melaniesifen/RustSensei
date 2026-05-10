from __future__ import annotations

import logging

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.enums import SetupCheckStatus
from rust_sensei.domain.setup import SetupCheck
from rust_sensei.dto.mappers import setup_check_to_dto
from rust_sensei.dto.setup import GetSetupStatusRequest, GetSetupStatusResponse
from rust_sensei.errors import validation_error
from rust_sensei.services.environment import EnvironmentProbe


class SetupService:
    def __init__(self, environment: EnvironmentProbe) -> None:
        self._environment = environment

    def get_setup_status(
        self,
        request: GetSetupStatusRequest,
    ) -> GetSetupStatusResponse:
        if request.learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=request.learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )

        checks = [
            self._python_check(),
            self._cargo_check(),
            self._state_dir_check(),
        ]
        if all(check.status == SetupCheckStatus.OK for check in checks):
            logging.getLogger(__name__).info("Setup status check passed")
        else:
            failed = [check.check_id for check in checks if check.status != SetupCheckStatus.OK]
            logging.getLogger(__name__).warning("Setup status check failed: %s", failed)

        return GetSetupStatusResponse(
            ready=all(check.status == SetupCheckStatus.OK for check in checks),
            checks=[setup_check_to_dto(check) for check in checks],
        )

    def _python_check(self) -> SetupCheck:
        major, minor, patch = self._environment.python_version()
        if (major, minor) >= (3, 11):
            return SetupCheck(
                check_id="python_version",
                status=SetupCheckStatus.OK,
                message=f"Python {major}.{minor}.{patch} is supported.",
            )

        return SetupCheck(
            check_id="python_version",
            status=SetupCheckStatus.ERROR,
            message=f"Python 3.11 or newer is required. Found {major}.{minor}.{patch}.",
        )

    def _cargo_check(self) -> SetupCheck:
        cargo_path = self._environment.cargo_path()
        if cargo_path:
            return SetupCheck(
                check_id="cargo_available",
                status=SetupCheckStatus.OK,
                message=f"cargo is available at {cargo_path}.",
            )

        return SetupCheck(
            check_id="cargo_available",
            status=SetupCheckStatus.ERROR,
            message="cargo was not found on PATH.",
        )

    def _state_dir_check(self) -> SetupCheck:
        if self._environment.state_dir_writable():
            return SetupCheck(
                check_id="state_dir_writable",
                status=SetupCheckStatus.OK,
                message="Rust Sensei state directory is writable.",
            )

        return SetupCheck(
            check_id="state_dir_writable",
            status=SetupCheckStatus.ERROR,
            message="Rust Sensei state directory is not writable.",
        )
