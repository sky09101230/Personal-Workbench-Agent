from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "literature-radar" / "scripts" / "zotero_cli.py"
SPEC = importlib.util.spec_from_file_location("literature_radar_zotero_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
zotero_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zotero_cli)


def test_resolve_prefers_path_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        zotero_cli.shutil,
        "which",
        lambda name: r"C:\tools\zotero-cli.exe" if name == "zotero-cli" else None,
    )

    assert zotero_cli.resolve_zotero_cli() == r"C:\tools\zotero-cli.exe"


def test_windows_probes_exe_name(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_which(name: str) -> str | None:
        calls.append(name)
        return r"C:\tools\zotero-cli.exe" if name == "zotero-cli.exe" else None

    monkeypatch.setattr(zotero_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(zotero_cli.shutil, "which", fake_which)

    assert zotero_cli.resolve_zotero_cli() == r"C:\tools\zotero-cli.exe"
    assert calls == ["zotero-cli", "zotero-cli.exe"]


def test_uv_tool_bin_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "zotero-cli.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return r"C:\tools\uv.exe" if name == "uv" else None

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(command, 0, str(tmp_path), "")

    monkeypatch.setattr(zotero_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(zotero_cli.shutil, "which", fake_which)
    monkeypatch.setattr(zotero_cli.subprocess, "run", fake_run)

    assert zotero_cli.resolve_zotero_cli() == str(executable.resolve())
    assert calls == [[r"C:\tools\uv.exe", "tool", "dir", "--bin"]]


def test_missing_cli_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zotero_cli.shutil, "which", lambda name: None)

    with pytest.raises(zotero_cli.ZoteroCliError, match="uv was not available"):
        zotero_cli.resolve_zotero_cli()


def test_preflight_runs_config_without_parsing_or_exposing_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_like_config = "private-config-output-that-must-not-be-returned"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["resolved-zotero", "config"]
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(command, 0, secret_like_config, "")

    monkeypatch.setattr(zotero_cli.subprocess, "run", fake_run)

    assert zotero_cli.preflight("resolved-zotero") == {
        "ok": True,
        "executable": "resolved-zotero",
        "config_ok": True,
    }
