import json

from rust_sensei import cli
from rust_sensei.errors import validation_error


def test_main_prints_help_when_command_is_missing(capsys):
    exit_code = cli.main([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "usage: rust-sensei" in output


def test_print_setup_status_returns_zero_when_ready(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _Factory(ready=True))

    exit_code = cli._print_setup_status(None)

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ready"] is True


def test_print_setup_status_returns_one_when_not_ready(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _Factory(ready=False))

    exit_code = cli._print_setup_status(None)

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["ready"] is False


def test_print_setup_status_logs_and_prints_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _ErrorFactory())

    exit_code = cli._print_setup_status(None)

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["error"]["error_code"] == "validation_error"


def test_print_doctor_returns_human_output_when_ready(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _Factory(ready=True))

    exit_code = cli._print_doctor(None)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Rust Sensei Doctor" in output
    assert "Status: ready" in output
    assert "[ok] python_version: Python is supported." in output
    assert "[ok] rustc_available: rustc is available." in output


def test_print_doctor_returns_one_when_not_ready(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _Factory(ready=False))

    exit_code = cli._print_doctor(None)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Status: not ready" in output
    assert "[error] cargo_available: cargo was not found on PATH." in output


def test_print_doctor_supports_json_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _Factory(ready=True))

    exit_code = cli._print_doctor(None, json_output=True)

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ready"] is True
    assert output["checks"][0]["check_id"] == "python_version"


def test_print_doctor_logs_and_prints_human_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _ErrorFactory())

    exit_code = cli._print_doctor(None)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Status: error" in output
    assert "bad input" in output


def test_main_routes_doctor_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServiceFactory", lambda state_dir: _Factory(ready=True))

    exit_code = cli.main(["doctor", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ready"] is True


class _Factory:
    def __init__(self, ready):
        self._ready = ready

    def setup_service(self):
        return _SetupService(self._ready)


class _SetupService:
    def __init__(self, ready):
        self._ready = ready

    def get_setup_status(self, request):
        return _Response(self._ready)


class _Response:
    def __init__(self, ready):
        self.ready = ready
        self.checks = [
            _Check("python_version", "ok", "Python is supported."),
            _Check("rustc_available", "ok", "rustc is available."),
            _Check(
                "cargo_available",
                "ok" if ready else "error",
                "cargo is available." if ready else "cargo was not found on PATH.",
            ),
        ]

    def model_dump(self, mode=None):
        return {
            "ready": self.ready,
            "checks": [
                {
                    "check_id": check.check_id,
                    "status": check.status.value,
                    "message": check.message,
                }
                for check in self.checks
            ],
        }


class _Status:
    def __init__(self, value):
        self.value = value


class _Check:
    def __init__(self, check_id, status, message):
        self.check_id = check_id
        self.status = _Status(status)
        self.message = message


class _ErrorFactory:
    def setup_service(self):
        return _ErrorSetupService()


class _ErrorSetupService:
    def get_setup_status(self, request):
        raise validation_error("bad input", field="learner_id")
