from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


class ZoteroCliError(RuntimeError):
    """Raised when the read-only Zotero CLI backend is unavailable."""


def _is_windows() -> bool:
    return os.name == "nt"


def resolve_zotero_cli() -> str:
    """Resolve zotero-cli without requiring a PowerShell alias or PATH edit."""
    resolved = shutil.which("zotero-cli")
    if resolved:
        return resolved

    if _is_windows():
        resolved = shutil.which("zotero-cli.exe")
        if resolved:
            return resolved

    uv = shutil.which("uv")
    if not uv:
        raise ZoteroCliError(
            "zotero-cli was not found on PATH and uv was not available to locate its tool bin directory"
        )

    try:
        completed = subprocess.run(
            [uv, "tool", "dir", "--bin"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ZoteroCliError(f"cannot run uv tool dir --bin: {exc}") from exc

    if completed.returncode != 0:
        detail = _safe_diagnostic(completed.stderr or completed.stdout)
        suffix = f": {detail}" if detail else ""
        raise ZoteroCliError(f"uv tool dir --bin failed{suffix}")

    bin_dir = completed.stdout.strip()
    if not bin_dir:
        raise ZoteroCliError("uv tool dir --bin returned an empty path")

    candidate = Path(bin_dir) / ("zotero-cli.exe" if _is_windows() else "zotero-cli")
    if not candidate.is_file():
        raise ZoteroCliError(f"zotero-cli was not found at {candidate}")
    return str(candidate.resolve())


def preflight(executable: str | None = None) -> dict[str, object]:
    """Run `zotero-cli config`; only its exit status is interpreted."""
    resolved = executable or resolve_zotero_cli()
    try:
        completed = subprocess.run(
            [resolved, "config"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ZoteroCliError(f"cannot run zotero-cli config: {exc}") from exc

    if completed.returncode != 0:
        detail = _safe_diagnostic(completed.stderr or completed.stdout)
        suffix = f": {detail}" if detail else ""
        raise ZoteroCliError(f"zotero-cli config failed{suffix}")
    return {"ok": True, "executable": resolved, "config_ok": True}


def _safe_diagnostic(value: str, limit: int = 600) -> str:
    text = value.strip()[-limit:]
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)[A-Z0-9_]*\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        text,
    )
    return " ".join(text.splitlines())


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve and preflight zotero-cli for Literature Radar")
    parser.add_argument("command", choices=("resolve", "preflight"))
    args = parser.parse_args()
    try:
        payload = (
            {"ok": True, "executable": resolve_zotero_cli()}
            if args.command == "resolve"
            else preflight()
        )
    except ZoteroCliError as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
