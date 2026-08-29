from __future__ import annotations

import importlib.util
import io
import json
from types import SimpleNamespace
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "literature-radar" / "scripts" / "zotero_cli.py"
SPEC = importlib.util.spec_from_file_location("literature_radar_zotero_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
zotero_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zotero_cli)


def completed(command: list[str], returncode: int, stdout: object, stderr: object = b"") -> subprocess.CompletedProcess[bytes]:
    out = stdout if isinstance(stdout, bytes) else json.dumps(stdout, ensure_ascii=False).encode("utf-8")
    err = stderr if isinstance(stderr, bytes) else str(stderr).encode("utf-8")
    return subprocess.CompletedProcess(command, returncode, out, err)


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


def test_uv_tool_bin_fallback_is_utf8_and_shell_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "zotero-cli.exe"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return r"C:\tools\uv.exe" if name == "uv" else None

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        assert "shell" not in kwargs
        assert kwargs["env"]["PYTHONUTF8"] == "1"  # type: ignore[index]
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"  # type: ignore[index]
        return completed(command, 0, str(tmp_path).encode("utf-8"))

    monkeypatch.setattr(zotero_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(zotero_cli.shutil, "which", fake_which)
    monkeypatch.setattr(zotero_cli.subprocess, "run", fake_run)

    assert zotero_cli.resolve_zotero_cli() == str(executable.resolve())
    assert calls == [[r"C:\tools\uv.exe", "tool", "dir", "--bin"]]


def test_missing_cli_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zotero_cli.shutil, "which", lambda name: None)

    with pytest.raises(zotero_cli.ZoteroCliError, match="uv was not available") as error:
        zotero_cli.resolve_zotero_cli()

    assert error.value.code == "not_found"


def test_preflight_uses_json_config_and_hides_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_config = {
        "ok": True,
        "command": "config",
        "schema": 1,
        "data": {"settings": {"private": "must-not-be-returned"}},
    }

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert command == ["resolved-zotero", "--json", "config"]
        assert "shell" not in kwargs
        assert kwargs["env"]["PYTHONUTF8"] == "1"  # type: ignore[index]
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"  # type: ignore[index]
        return completed(command, 0, private_config)

    monkeypatch.setattr(zotero_cli.subprocess, "run", fake_run)

    result = zotero_cli.preflight("resolved-zotero")

    assert result == {
        "ok": True,
        "executable": "resolved-zotero",
        "config_ok": True,
        "utf8": True,
    }
    assert "settings" not in result


def test_run_json_decodes_utf8_independently_of_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "ok": True,
        "command": "search",
        "schema": 1,
        "data": {
            "count": 1,
            "items": [{"title": "© Matrix \\D — diffractive network"}],
        },
    }

    monkeypatch.setattr(
        zotero_cli.subprocess,
        "run",
        lambda command, **kwargs: completed(command, 0, payload),
    )

    result = zotero_cli.run_json(
        ["search", "diffractive", "--limit", "10"], executable="zotero"
    )

    assert result["data"]["items"][0]["title"] == "© Matrix \\D — diffractive network"  # type: ignore[index]


def test_run_json_rejects_malformed_output_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        zotero_cli.subprocess,
        "run",
        lambda command, **kwargs: completed(command, 0, b'{"ok":true,"title":"bad\\D"}'),
    )

    with pytest.raises(zotero_cli.ZoteroCliError) as error:
        zotero_cli.run_json(["search", "query"], executable="zotero")

    assert error.value.code == "invalid_json"
    assert "bad" not in str(error.value)


def test_run_json_requires_exit_envelope_agreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"ok": False, "command": "search", "schema": 1, "error": {"message": "failed", "code": "X"}}
    monkeypatch.setattr(
        zotero_cli.subprocess,
        "run",
        lambda command, **kwargs: completed(command, 0, payload),
    )

    with pytest.raises(zotero_cli.ZoteroCliError) as error:
        zotero_cli.run_json(["search", "query"], executable="zotero")

    assert error.value.code == "exit_envelope_mismatch"


def test_metadata_uses_machine_readable_command(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"ok": True, "command": "get", "schema": 1, "data": {"data": {"title": "© Paper"}}}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert command == ["zotero", "--json", "get", "metadata", "KEY123"]
        return completed(command, 0, payload)

    monkeypatch.setattr(zotero_cli.subprocess, "run", fake_run)

    assert zotero_cli.metadata("KEY123", executable="zotero")["data"] == payload["data"]


def test_batch_search_isolates_one_query_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(query: str, **kwargs: object) -> dict[str, object]:
        if query == "bad":
            raise zotero_cli.ZoteroCliError("invalid json", code="invalid_json", command=("search", query))
        return {"ok": True, "data": {"count": 1, "items": [{"title": query}]}}

    monkeypatch.setattr(zotero_cli, "search", fake_search)

    result = zotero_cli.batch_search(
        ["good", "bad", "also-good"], executable="zotero", limit=10
    )

    assert result["ok"] is True
    assert result["data"]["successful_queries"] == 2  # type: ignore[index]
    assert result["data"]["failed_queries"] == 1  # type: ignore[index]
    assert result["data"]["degraded"] is True  # type: ignore[index]
    statuses = [row["status"] for row in result["data"]["queries"]]  # type: ignore[index]
    assert statuses == ["success", "failed", "success"]


def test_batch_search_fails_only_when_all_queries_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(query: str, **kwargs: object) -> dict[str, object]:
        raise zotero_cli.ZoteroCliError("unavailable", code="unavailable")

    monkeypatch.setattr(zotero_cli, "search", fail)

    result = zotero_cli.batch_search(["one", "two"], executable="zotero")

    assert result["ok"] is False
    assert result["data"]["successful_queries"] == 0  # type: ignore[index]
    assert result["data"]["failed_queries"] == 2  # type: ignore[index]


def test_safe_diagnostic_redacts_secret_assignments() -> None:
    label = "SERVICE_" + "SECRET"
    sensitive_value = "dummy-sensitive-value"
    diagnostic = zotero_cli._safe_diagnostic(f"{label}={sensitive_value}")

    assert sensitive_value not in diagnostic
    assert "[REDACTED]" in diagnostic

def test_emit_json_is_ascii_safe_and_round_trips_unicode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.BytesIO()
    monkeypatch.setattr(zotero_cli.sys, "stdout", SimpleNamespace(buffer=buffer))

    zotero_cli._emit_json({"title": "© Meta‐Devices"})

    raw = buffer.getvalue()
    assert all(byte < 128 for byte in raw)
    assert json.loads(raw)["title"] == "© Meta‐Devices"
