from pathlib import Path

API_UNIT = Path("deploy/systemd/flight-hunter-api.service")
WORKER_UNIT = Path("deploy/systemd/flight-hunter-worker@.service")


def test_systemd_units_use_env_file_and_no_inline_secrets() -> None:
    for path in (API_UNIT, WORKER_UNIT):
        unit = path.read_text(encoding="utf-8")

        assert "EnvironmentFile=/etc/flight-hunter/flight-hunter.env" in unit
        assert "API_TOKEN=" not in unit
        assert "BOT_TOKEN=" not in unit
        assert "SECRET=" not in unit
        assert "PASSWORD=" not in unit


def test_systemd_units_have_supervisor_restart_and_hardening() -> None:
    for path in (API_UNIT, WORKER_UNIT):
        unit = path.read_text(encoding="utf-8")

        assert "Restart=on-failure" in unit
        assert "KillSignal=SIGTERM" in unit
        assert "NoNewPrivileges=true" in unit
        assert "ProtectSystem=strict" in unit
        assert "ReadWritePaths=/var/lib/flight-hunter" in unit


def test_worker_systemd_template_runs_one_role_lane_per_instance() -> None:
    unit = WORKER_UNIT.read_text(encoding="utf-8")

    assert "Description=Flight Hunter worker lane %i" in unit
    assert "flight-hunter-worker --role %i --loop" in unit
    assert "--role browser" not in unit
    assert "--role watch" not in unit
    assert "--role deal" not in unit
