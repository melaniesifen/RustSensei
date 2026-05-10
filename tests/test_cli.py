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

    def model_dump(self, mode=None):
        return {"ready": self.ready, "checks": []}


class _ErrorFactory:
    def setup_service(self):
        return _ErrorSetupService()


class _ErrorSetupService:
    def get_setup_status(self, request):
        raise validation_error("bad input", field="learner_id")
