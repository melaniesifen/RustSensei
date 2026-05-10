import json

from rust_sensei import cli


def test_setup_status_reports_invalid_state_dir_without_crashing(capsys):
    exit_code = cli.main(["--state-dir", "/dev/null", "setup-status"])

    output = json.loads(capsys.readouterr().out)
    state_check = next(
        check for check in output["checks"] if check["check_id"] == "state_dir_writable"
    )
    assert exit_code == 1
    assert output["ready"] is False
    assert state_check["status"] == "error"
