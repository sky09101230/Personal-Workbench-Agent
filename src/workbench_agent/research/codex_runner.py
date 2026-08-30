from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from ..errors import CodexExecutionError


def _is_windows() -> bool:
    return os.name == "nt"


def _resolve_executable(executable: str) -> str:
    resolved = shutil.which(executable)
    if resolved is not None:
        return resolved

    path = Path(executable).expanduser()
    if _is_windows() and not path.suffix:
        for suffix in (".cmd", ".exe"):
            resolved = shutil.which(f"{executable}{suffix}")
            if resolved is not None:
                return resolved

    if path.is_absolute() and path.is_file():
        if _is_windows() or os.access(path, os.X_OK):
            return str(path)

    raise CodexExecutionError(f"Codex executable was not found: {executable}")


class CodexResearchRunner:
    def __init__(self, executable: str = "codex", *, timeout: float = 900.0) -> None:
        self.executable = _resolve_executable(executable)
        self.timeout = timeout

    def require_mcp(self, name: str) -> None:
        try:
            completed = subprocess.run(
                [self.executable, "mcp", "get", name, "--json"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=min(self.timeout, 30.0),
                check=False,
            )
        except FileNotFoundError as exc:
            raise CodexExecutionError(
                f"Codex executable was not found: {self.executable}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexExecutionError(
                f"Timed out checking Codex MCP server: {name}"
            ) from exc
        except OSError as exc:
            raise CodexExecutionError(f"Cannot check Codex MCP configuration: {exc}") from exc
        if completed.returncode != 0:
            raise CodexExecutionError(
                f"Codex MCP server is not configured: {name}"
            )

    def run(
        self, instruction: str, output_schema: Mapping[str, object]
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="workbench-research-") as temp_dir:
            directory = Path(temp_dir)
            schema_path = directory / "schema.json"
            result_path = directory / "result.json"
            schema_path.write_text(json.dumps(output_schema), encoding="utf-8")
            command = [
                self.executable,
                "--search",
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(result_path),
                "-",
            ]
            try:
                completed = subprocess.run(
                    command,
                    input=instruction,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise CodexExecutionError(
                    f"Codex executable was not found: {self.executable}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise CodexExecutionError(
                    f"Codex research timed out after {self.timeout:g} seconds"
                ) from exc
            except KeyboardInterrupt as exc:
                raise CodexExecutionError("Codex research was interrupted") from exc
            except OSError as exc:
                raise CodexExecutionError(f"Cannot start Codex: {exc}") from exc

            if completed.returncode != 0:
                detail = _safe_diagnostic(completed.stderr or completed.stdout)
                suffix = f": {detail}" if detail else ""
                raise CodexExecutionError(
                    f"Codex exited with status {completed.returncode}{suffix}"
                )
            try:
                output = result_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise CodexExecutionError("Codex did not write a structured result") from exc
            if not output.strip():
                raise CodexExecutionError("Codex returned an empty structured result")
            try:
                value = json.loads(output)
            except json.JSONDecodeError as exc:
                raise CodexExecutionError("Codex returned malformed structured JSON") from exc
            if not isinstance(value, dict):
                raise CodexExecutionError("Codex structured result must be a JSON object")
            return value


def _safe_diagnostic(value: str, limit: int = 1200) -> str:
    text = value.strip()[-limit:]
    text = re.sub(
        r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[REDACTED]", text
    )
    text = re.sub(
        r"(?i)([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)[A-Z0-9_]*\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        text,
    )
    return " ".join(text.splitlines())
