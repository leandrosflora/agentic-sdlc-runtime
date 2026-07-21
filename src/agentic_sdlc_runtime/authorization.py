"""OPA policy decision point (PDP) for the shared runtime tool loop.

The canonical rego in agentic-sdlc-reference-architecture/policies stays the
single source of truth -- nothing here re-implements policy logic. Two
evaluation modes are supported: the `opa` CLI as a subprocess (developer
machines, CI) and a remote OPA server reached over HTTP (sidecar or central
PDP). When the runtime is constructed without an authorizer, only the
per-agent tool grants are enforced, preserving the previous behavior.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POLICY_QUERY = "data.agentic_sdlc.authorization.allow"
POLICY_ENV_VAR = "SDLC_POLICY_PATH"
OPA_URL_ENV_VAR = "SDLC_OPA_URL"
DEFAULT_SIBLING_POLICY = (
    Path("..") / "agentic-sdlc-reference-architecture" / "policies" / "agent_authorization.rego"
)


class PolicyUnavailableError(RuntimeError):
    """Raised when the policy cannot be evaluated, which is never a silent allow."""


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    action: str
    raw: dict[str, Any]


class Authorizer(ABC):
    @abstractmethod
    def check(self, input_doc: dict[str, Any]) -> AuthorizationResult:
        raise NotImplementedError


def resolve_policy_path(configured: str | Path | None = None) -> Path:
    configured = configured or os.environ.get(POLICY_ENV_VAR)
    if configured:
        path = Path(configured)
    else:
        repo_root = Path(__file__).resolve().parents[2]
        path = repo_root / DEFAULT_SIBLING_POLICY
    if not path.is_file():
        raise PolicyUnavailableError(
            f"policy file not found at '{path}'; set {POLICY_ENV_VAR} or check out "
            "agentic-sdlc-reference-architecture as a sibling repository"
        )
    return path


class OpaCliAuthorizer(Authorizer):
    """Evaluates the canonical policy with the `opa` CLI, like the agent repos do."""

    def __init__(self, policy_path: str | Path | None = None):
        self.policy_path = resolve_policy_path(policy_path)

    def check(self, input_doc: dict[str, Any]) -> AuthorizationResult:
        opa_bin = shutil.which("opa")
        if not opa_bin:
            raise PolicyUnavailableError("the 'opa' CLI was not found on PATH")
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(input_doc, tmp)
            result = subprocess.run(
                [opa_bin, "eval", "--format", "json", "--data", str(self.policy_path),
                 "--input", tmp_path, POLICY_QUERY],
                capture_output=True, text=True,
            )
        finally:
            os.unlink(tmp_path)
        if result.returncode != 0:
            raise PolicyUnavailableError(f"`opa eval` failed: {result.stderr or result.stdout}")
        parsed = json.loads(result.stdout)
        try:
            allowed = bool(parsed["result"][0]["expressions"][0]["value"])
        except (KeyError, IndexError, TypeError) as exc:
            raise PolicyUnavailableError(f"unexpected `opa eval` output: {result.stdout}") from exc
        return AuthorizationResult(allowed=allowed, action=input_doc.get("action", ""), raw=parsed)


class OpaHttpAuthorizer(Authorizer):
    """Queries a running OPA server (sidecar or central PDP) over its data API."""

    def __init__(self, base_url: str | None = None, timeout: int = 10):
        self.base_url = (base_url or os.environ.get(OPA_URL_ENV_VAR, "")).rstrip("/")
        if not self.base_url:
            raise PolicyUnavailableError(f"set {OPA_URL_ENV_VAR} or pass base_url")
        self.timeout = timeout
        self.decision_path = "/v1/data/" + POLICY_QUERY.removeprefix("data.").replace(".", "/")

    def check(self, input_doc: dict[str, Any]) -> AuthorizationResult:
        request = urllib.request.Request(
            f"{self.base_url}{self.decision_path}",
            data=json.dumps({"input": input_doc}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
        except OSError as exc:
            raise PolicyUnavailableError(f"OPA server unreachable at {self.base_url}: {exc}") from exc
        # An undefined decision comes back without "result"; that is a deny.
        return AuthorizationResult(
            allowed=bool(payload.get("result", False)),
            action=input_doc.get("action", ""),
            raw=payload,
        )


def authorizer_from_environment() -> Authorizer | None:
    """OPA server if SDLC_OPA_URL is set, `opa` CLI if SDLC_POLICY_PATH is set, else None."""
    if os.environ.get(OPA_URL_ENV_VAR):
        return OpaHttpAuthorizer()
    if os.environ.get(POLICY_ENV_VAR):
        return OpaCliAuthorizer()
    return None
