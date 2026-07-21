from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from .demo_environment import DemoEnvironment
from .quality import GovernedCommandRunner


class HttpHealthObserver:
    def __init__(self, url: str, *, attempts: int = 5, interval: float = 1.0, timeout: float = 3.0):
        if not url.startswith(("http://", "https://")):
            raise ValueError("health URL must use http or https")
        self.url = url
        self.attempts = attempts
        self.interval = interval
        self.timeout = timeout

    def observe(self) -> dict:
        observations = []
        for attempt in range(1, self.attempts + 1):
            try:
                with urllib.request.urlopen(self.url, timeout=self.timeout) as response:
                    body = response.read(4096).decode(errors="replace")
                    healthy = 200 <= response.status < 300
                    observations.append({"attempt": attempt, "status": response.status, "body": body})
                    if healthy:
                        return {"healthy": True, "url": self.url, "attempts": observations}
            except (urllib.error.URLError, TimeoutError) as error:
                observations.append({"attempt": attempt, "error": type(error).__name__})
            if attempt < self.attempts:
                time.sleep(self.interval)
        return {"healthy": False, "url": self.url, "attempts": observations}


class ExternalDemoEnvironment(DemoEnvironment):
    """Demo adapter backed by explicit deploy/rollback commands and HTTP telemetry."""

    def __init__(self, path: str | Path, *, runner: GovernedCommandRunner,
                 deploy_command: list[str], rollback_command: list[str],
                 observer: HttpHealthObserver):
        super().__init__(path)
        self.runner = runner
        self.deploy_command = deploy_command
        self.rollback_command = rollback_command
        self.observer = observer

    def deploy(self, digest: str) -> dict:
        evidence = asdict(self.runner.run(
            self.deploy_command, extra_env={"ARTIFACT_DIGEST": digest},
        ))
        state = super().deploy(digest)
        state["history"][-1]["command_evidence"] = evidence
        self._write(state)
        return state

    def observe(self, healthy: bool | None = None) -> dict:
        result = {"healthy": healthy} if healthy is not None else self.observer.observe()
        state = self._read()
        state["history"].append({
            "action": "observe", "digest": state["current_digest"], **result,
        })
        self._write(state)
        return {"digest": state["current_digest"], **result}

    def rollback(self) -> dict:
        state = self._read()
        target = state["previous_digest"] or ""
        evidence = asdict(self.runner.run(
            self.rollback_command, extra_env={"ARTIFACT_DIGEST": target},
        ))
        state = super().rollback()
        state["history"][-1]["command_evidence"] = evidence
        self._write(state)
        return state
