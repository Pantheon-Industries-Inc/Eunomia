"""VLM client — bounded perception calls to an OpenRouter-hosted vision model."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


class CostBudgetExceeded(Exception):
    pass


class VLMError(Exception):
    pass


DEFAULT_MODEL = "google/gemini-2.0-flash-001"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class VLMClient:
    """Async VLM client for OpenRouter-hosted vision models."""

    api_key: str
    model: str = ""
    max_retries: int = 3
    timeout_s: float = 30.0
    cost_budget_usd: float = 1.0
    _cumulative_cost: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.model:
            self.model = os.environ.get("EUNOMIA_QC_VLM_MODEL", DEFAULT_MODEL)

    @property
    def cumulative_cost(self) -> float:
        return self._cumulative_cost

    async def ask(
        self,
        question: str,
        images: list[bytes],
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if self._cumulative_cost >= self.cost_budget_usd:
            raise CostBudgetExceeded(
                f"VLM cost budget exceeded: ${self._cumulative_cost:.4f} >= ${self.cost_budget_usd:.2f}"
            )

        content: list[dict[str, Any]] = []
        for img in images:
            b64 = base64.b64encode(img).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }
            )
        content.append({"type": "text", "text": question})

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a quality-control vision assistant. Answer the question about the "
                        "provided image(s). Respond ONLY with valid JSON matching this schema: "
                        '{"answer": <boolean>, "reason": "<string>"}. '
                        "Be precise and concise."
                    ),
                },
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.post(
                        OPENROUTER_URL, json=payload, headers=headers
                    )

                if resp.status_code == 429 or resp.status_code >= 500:
                    import asyncio

                    delay = min(2**attempt * 0.5, 8.0)
                    await asyncio.sleep(delay)
                    last_err = VLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    continue

                if resp.status_code >= 400:
                    raise VLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")

                body = resp.json()

                usage = body.get("usage") or {}
                cost = usage.get("total_cost") or 0.0
                self._cumulative_cost += float(cost)

                message = body["choices"][0]["message"]["content"]
                import json

                parsed = json.loads(message)

                if "answer" not in parsed or "reason" not in parsed:
                    if attempt < self.max_retries - 1:
                        last_err = VLMError(f"Malformed VLM response: {parsed}")
                        continue
                    return {
                        "answer": False,
                        "reason": f"Malformed response: {message[:200]}",
                    }

                return {
                    "answer": bool(parsed["answer"]),
                    "reason": str(parsed["reason"]),
                }

            except httpx.TimeoutException:
                last_err = VLMError("Request timed out")
                if attempt < self.max_retries - 1:
                    continue
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                last_err = VLMError(f"Response parse error: {exc}")
                if attempt < self.max_retries - 1:
                    continue

        return {
            "answer": False,
            "reason": f"VLM unavailable after {self.max_retries} retries: {last_err}",
        }


def make_vlm_client() -> VLMClient | None:
    """Create a VLM client from environment, or None if API key is missing."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return None
    return VLMClient(api_key=api_key)
