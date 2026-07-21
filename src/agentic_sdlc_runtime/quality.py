from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CommandEvidence:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandRejected(PermissionError):
    pass


class GovernedCommandRunner:
    """Runs explicit argv without a shell, inside one workspace and an executable allowlist."""

    def __init__(self, workspace: str | Path, allowed: Iterable[str] = ("python", "pytest", "ruff")):
        self.workspace = Path(workspace).resolve()
        self.allowed = frozenset(allowed)

    def run(self, argv: list[str], *, timeout: int = 300,
            extra_env: dict[str, str] | None = None) -> CommandEvidence:
        if not argv or Path(argv[0]).name not in self.allowed:
            raise CommandRejected("executable is not allowed")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "CI": "true",
        }
        env.update(extra_env or {})
        completed = subprocess.run(
            argv, cwd=self.workspace, env=env, shell=False, text=True,
            capture_output=True, timeout=timeout, check=False,
        )
        evidence = CommandEvidence(
            argv=argv, returncode=completed.returncode,
            stdout=completed.stdout[-20000:], stderr=completed.stderr[-20000:],
        )
        if completed.returncode:
            raise RuntimeError(f"command failed: {asdict(evidence)}")
        return evidence


class QualityGates:
    def __init__(self, runner: GovernedCommandRunner):
        self.runner = runner

    def run(self, commands: list[list[str]]) -> list[dict]:
        return [asdict(self.runner.run(command)) for command in commands]
