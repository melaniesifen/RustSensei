from rust_sensei.services.environment import EnvironmentProbe


def test_environment_probe_reports_python_version(tmp_path):
    probe = EnvironmentProbe(tmp_path)

    major, minor, patch = probe.python_version()

    assert isinstance(major, int)
    assert isinstance(minor, int)
    assert isinstance(patch, int)


def test_environment_probe_reports_state_dir_writable(tmp_path):
    probe = EnvironmentProbe(tmp_path)

    assert probe.state_dir_writable() is True
