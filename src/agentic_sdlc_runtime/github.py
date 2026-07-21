from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class GitHubIssue:
    number: int
    title: str
    body: str
    author: str
    html_url: str


Transport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class GitHubClient:
    """Small GitHub REST adapter; credentials never enter runtime evidence."""

    def __init__(self, repository: str, token: str | None = None,
                 api_url: str | None = None, transport: Transport | None = None):
        if repository.count("/") != 1:
            raise ValueError("repository must use owner/name")
        self.repository = repository
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL", "https://api.github.com")).rstrip("/")
        self.transport = transport
        if not self.token and transport is None:
            raise ValueError("GITHUB_TOKEN is required")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.transport:
            return self.transport(method, path, payload)
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.api_url}{path}", data=data, method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "agentic-sdlc-runtime",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:1000]
            raise RuntimeError(f"GitHub API {error.code}: {detail}") from error
        return json.loads(raw.decode()) if raw else {}

    def get_issue(self, number: int) -> GitHubIssue:
        data = self._request("GET", f"/repos/{self.repository}/issues/{number}")
        if "pull_request" in data:
            raise ValueError("expected issue, received pull request")
        return GitHubIssue(
            number=int(data["number"]), title=data["title"], body=data.get("body") or "",
            author=data["user"]["login"], html_url=data["html_url"],
        )

    def comment(self, number: int, body: str) -> str:
        data = self._request("POST", f"/repos/{self.repository}/issues/{number}/comments", {"body": body})
        return data["html_url"]

    def check(self, head_sha: str, *, name: str, status: str,
              conclusion: str | None = None, summary: str = "") -> int:
        payload: dict[str, Any] = {
            "name": name, "head_sha": head_sha, "status": status,
            "output": {"title": name, "summary": summary[:65000]},
        }
        if conclusion is not None:
            payload["conclusion"] = conclusion
        data = self._request("POST", f"/repos/{self.repository}/check-runs", payload)
        return int(data["id"])
