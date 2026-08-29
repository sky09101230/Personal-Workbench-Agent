from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class ZoteroCliError(RuntimeError):
    """A safe, structured failure from the read-only Zotero CLI backend."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "zotero_cli_error",
        command: Sequence[str] = (),
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.command = tuple(command)
        self.returncode = returncode

    def to_payload(self) -> dict[str, object]:
        return {
            "message": str(self),
            "code": self.code,
            "command": list(self.command),
            "returncode": self.returncode,
        }


def _is_windows() -> bool:
    return os.name == "nt"


def _utf8_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("NO_COLOR", "1")
    return env


def _decode_utf8(value: bytes, *, label: str, command: Sequence[str]) -> str:
    try:
        return value.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ZoteroCliError(
            f"{label} was not valid UTF-8 at byte {exc.start}",
            code="invalid_utf8",
            command=command,
        ) from exc


def _run_process(command: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(command),
            env=_utf8_env(),
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ZoteroCliError(
            f"command timed out after {timeout:g} seconds",
            code="timeout",
            command=command,
        ) from exc
    except OSError as exc:
        raise ZoteroCliError(
            f"cannot execute command: {exc}",
            code="execution_error",
            command=command,
        ) from exc


def resolve_zotero_cli() -> str:
    """Resolve zotero-cli without a PowerShell alias or a manual PATH edit."""
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
            "zotero-cli was not found on PATH and uv was not available to locate its tool bin directory",
            code="not_found",
        )

    command = [uv, "tool", "dir", "--bin"]
    completed = _run_process(command, timeout=30.0)
    stdout = _decode_utf8(completed.stdout, label="uv stdout", command=command)
    if completed.returncode != 0:
        stderr = _safe_diagnostic(
            _decode_utf8(completed.stderr, label="uv stderr", command=command)
        )
        suffix = f": {stderr}" if stderr else ""
        raise ZoteroCliError(
            f"uv tool dir --bin failed{suffix}",
            code="uv_failed",
            command=command,
            returncode=completed.returncode,
        )

    bin_dir = stdout.strip()
    if not bin_dir:
        raise ZoteroCliError(
            "uv tool dir --bin returned an empty path",
            code="uv_empty_path",
            command=command,
        )

    candidate = Path(bin_dir) / ("zotero-cli.exe" if _is_windows() else "zotero-cli")
    if not candidate.is_file():
        raise ZoteroCliError(
            f"zotero-cli was not found at {candidate}",
            code="not_found",
            command=command,
        )
    return str(candidate.resolve())


def run_json(
    args: Sequence[str],
    *,
    executable: str | None = None,
    timeout: float = 60.0,
) -> dict[str, object]:
    """Run one machine-readable read command with console-independent UTF-8."""
    resolved = executable or resolve_zotero_cli()
    command = [resolved, "--json", *args]
    completed = _run_process(command, timeout=timeout)
    stdout = _decode_utf8(completed.stdout, label="zotero-cli stdout", command=command)
    stderr = _safe_diagnostic(
        _decode_utf8(completed.stderr, label="zotero-cli stderr", command=command)
    )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        suffix = f"; stderr: {stderr}" if stderr else ""
        raise ZoteroCliError(
            f"zotero-cli returned invalid JSON at character {exc.pos}{suffix}",
            code="invalid_json",
            command=args,
            returncode=completed.returncode,
        ) from exc
    if not isinstance(payload, dict):
        raise ZoteroCliError(
            "zotero-cli JSON envelope must be an object",
            code="invalid_envelope",
            command=args,
            returncode=completed.returncode,
        )

    ok = payload.get("ok") is True
    if ok != (completed.returncode == 0):
        raise ZoteroCliError(
            "zotero-cli exit code and JSON ok field disagreed",
            code="exit_envelope_mismatch",
            command=args,
            returncode=completed.returncode,
        )
    if not ok:
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        raise ZoteroCliError(
            _safe_diagnostic(str(message or "zotero-cli command failed")),
            code=str(code or "command_failed"),
            command=args,
            returncode=completed.returncode,
        )
    return payload


def preflight(executable: str | None = None) -> dict[str, object]:
    """Validate executable/config without returning sensitive settings."""
    resolved = executable or resolve_zotero_cli()
    run_json(["config"], executable=resolved, timeout=30.0)
    return {"ok": True, "executable": resolved, "config_ok": True, "utf8": True}


def search(
    query: str,
    *,
    limit: int = 10,
    detail: str = "summary",
    executable: str | None = None,
) -> dict[str, object]:
    if limit <= 0 or limit > 100:
        raise ZoteroCliError("limit must be between 1 and 100", code="invalid_limit")
    if detail not in {"keys_only", "summary", "full"}:
        raise ZoteroCliError("unsupported detail level", code="invalid_detail")
    return run_json(
        ["search", query, "--limit", str(limit), "--detail", detail],
        executable=executable,
    )


def metadata(item_key: str, *, executable: str | None = None) -> dict[str, object]:
    return run_json(["get", "metadata", item_key], executable=executable)


def batch_search(
    queries: Sequence[str],
    *,
    limit: int = 10,
    detail: str = "summary",
    executable: str | None = None,
) -> dict[str, object]:
    """Isolate query failures while preserving successful Library Context."""
    resolved = executable or resolve_zotero_cli()
    results: list[dict[str, object]] = []
    successful = 0
    for query in queries:
        try:
            payload = search(
                query,
                limit=limit,
                detail=detail,
                executable=resolved,
            )
        except ZoteroCliError as exc:
            results.append(
                {"query": query, "status": "failed", "error": exc.to_payload()}
            )
        else:
            successful += 1
            data = payload.get("data")
            count = data.get("count") if isinstance(data, dict) else None
            items = data.get("items") if isinstance(data, dict) else None
            results.append(
                {
                    "query": query,
                    "status": "success",
                    "count": count,
                    "items": items if isinstance(items, list) else [],
                }
            )
    failed = len(results) - successful
    return {
        "ok": successful > 0,
        "command": "batch-search",
        "schema": 1,
        "data": {
            "executable": resolved,
            "limit": limit,
            "detail": detail,
            "successful_queries": successful,
            "failed_queries": failed,
            "degraded": failed > 0,
            "queries": results,
        },
    }


def _safe_diagnostic(value: str, limit: int = 600) -> str:
    text = value.strip()[-limit:]
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)[A-Z0-9_]*\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        text,
    )
    return " ".join(text.splitlines())


def _emit_json(payload: dict[str, object]) -> None:
    data = json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n"
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stable read-only zotero-cli support for Literature Radar"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("resolve")
    subparsers.add_parser("preflight")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument(
        "--detail", choices=("keys_only", "summary", "full"), default="summary"
    )

    metadata_parser = subparsers.add_parser("metadata")
    metadata_parser.add_argument("item_key")

    batch_parser = subparsers.add_parser("batch-search")
    batch_parser.add_argument("--query", action="append", required=True)
    batch_parser.add_argument("--limit", type=int, default=10)
    batch_parser.add_argument(
        "--detail", choices=("keys_only", "summary", "full"), default="summary"
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "resolve":
            payload: dict[str, object] = {
                "ok": True,
                "executable": resolve_zotero_cli(),
            }
        elif args.command == "preflight":
            payload = preflight()
        elif args.command == "search":
            payload = search(args.query, limit=args.limit, detail=args.detail)
        elif args.command == "metadata":
            payload = metadata(args.item_key)
        else:
            payload = batch_search(args.query, limit=args.limit, detail=args.detail)
    except ZoteroCliError as exc:
        payload = {"ok": False, "error": exc.to_payload()}
        _emit_json(payload)
        return 1
    _emit_json(payload)
    return 0 if payload.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
