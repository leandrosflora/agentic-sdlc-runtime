from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from .models import ModelResponse


class ModelGateway(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, context: str, input_data: dict[str, Any]) -> ModelResponse:
        raise NotImplementedError


class FakeModelGateway(ModelGateway):
    """Deterministic model for tests and offline golden paths."""

    def __init__(self, responses: list[ModelResponse] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def complete(self, system_prompt: str, context: str, input_data: dict[str, Any]) -> ModelResponse:
        self.calls.append({"system_prompt": system_prompt, "context": context, "input_data": input_data})
        if self.responses:
            return self.responses.pop(0)
        content = json.dumps({
            "summary": f"Processed by fake model: {input_data.get('task', 'task')}",
            "status": "proposed",
        })
        return ModelResponse(content=content, model="fake", input_tokens=len(context) // 4, output_tokens=len(content) // 4)


class OpenAICompatibleGateway(ModelGateway):
    """Real HTTP gateway for OpenAI-compatible chat completion APIs.

    Works with OpenAI, Azure-compatible proxies, vLLM and corporate gateways.
    Credentials are read from the environment and never included in context.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int = 60):
        self.base_url = (base_url or os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("MODEL_API_KEY")
        self.model = model or os.environ.get("MODEL_NAME")
        self.timeout = timeout
        if not self.api_key or not self.model:
            raise ValueError("MODEL_API_KEY and MODEL_NAME are required")

    def complete(self, system_prompt: str, context: str, input_data: dict[str, Any]) -> ModelResponse:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"context": context, "input": input_data})},
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode())
        choice = payload["choices"][0]["message"]
        usage = payload.get("usage", {})
        return ModelResponse(
            content=choice.get("content", "{}"),
            tool_calls=choice.get("tool_calls", []),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=payload.get("model", self.model),
        )
