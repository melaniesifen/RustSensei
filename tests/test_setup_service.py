from pathlib import Path

from rust_sensei.domain.enums import SetupCheckStatus
from rust_sensei.dto.setup import GetSetupStatusRequest
from rust_sensei.services.environment import EnvironmentProbe
from rust_sensei.services.setup_service import SetupService


class FakeEnvironment(EnvironmentProbe):
    def __init__(
        self,
        python_version=(3, 11, 8),
        rustc_path="/usr/bin/rustc",
        cargo_path="/usr/bin/cargo",
        state_dir_writable=True,
    ):
        self._python_version = python_version
        self._rustc_path = rustc_path
        self._cargo_path = cargo_path
        self._state_dir_writable = state_dir_writable
        super().__init__(Path("/unused"))

    def python_version(self):
        return self._python_version

    def cargo_path(self):
        return self._cargo_path

    def rustc_path(self):
        return self._rustc_path

    def state_dir_writable(self):
        return self._state_dir_writable


def test_setup_status_ready_when_all_checks_pass():
    service = SetupService(FakeEnvironment())

    response = service.get_setup_status(GetSetupStatusRequest())

    assert response.ready is True
    assert [check.status for check in response.checks] == [
        SetupCheckStatus.OK,
        SetupCheckStatus.OK,
        SetupCheckStatus.OK,
        SetupCheckStatus.OK,
    ]


def test_setup_status_not_ready_when_python_is_too_old():
    service = SetupService(FakeEnvironment(python_version=(3, 9, 6)))

    response = service.get_setup_status(GetSetupStatusRequest())

    assert response.ready is False
    assert response.checks[0].check_id == "python_version"
    assert response.checks[0].status == SetupCheckStatus.ERROR


def test_setup_status_not_ready_when_rustc_is_missing():
    service = SetupService(FakeEnvironment(rustc_path=None))

    response = service.get_setup_status(GetSetupStatusRequest())

    assert response.ready is False
    assert response.checks[1].check_id == "rustc_available"
    assert response.checks[1].status == SetupCheckStatus.ERROR


def test_setup_status_not_ready_when_cargo_is_missing():
    service = SetupService(FakeEnvironment(cargo_path=None))

    response = service.get_setup_status(GetSetupStatusRequest())

    assert response.ready is False
    assert response.checks[2].check_id == "cargo_available"
    assert response.checks[2].status == SetupCheckStatus.ERROR


def test_setup_status_not_ready_when_state_dir_is_not_writable():
    service = SetupService(FakeEnvironment(state_dir_writable=False))

    response = service.get_setup_status(GetSetupStatusRequest())

    assert response.ready is False
    assert response.checks[3].check_id == "state_dir_writable"
    assert response.checks[3].status == SetupCheckStatus.ERROR
