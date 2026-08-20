"""CLI smoke tests exercise only offline commands."""

from typer.testing import CliRunner

from hivemind.cli import app

runner = CliRunner()


def test_doctor_fake_is_offline_and_successful(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor", "--provider", "fake"])

    assert result.exit_code == 0
    assert "Provider (fake)" in result.stdout
    assert "PASS" in result.stdout
