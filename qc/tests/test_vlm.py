"""Tests for VLM client (mocked HTTP, no real API calls)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from eunomia_qc.vlm import CostBudgetExceeded, VLMClient, make_vlm_client


def _mock_response(
    answer: bool, reason: str, cost: float = 0.01, status_code: int = 200
):
    """Create a mock httpx response."""
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"answer": answer, "reason": reason})
                    }
                }
            ],
            "usage": {"total_cost": cost},
        }
    )
    resp.json.return_value = {
        "choices": [
            {"message": {"content": json.dumps({"answer": answer, "reason": reason})}}
        ],
        "usage": {"total_cost": cost},
    }
    return resp


class TestVLMClient:
    def test_successful_ask(self) -> None:
        client = VLMClient(api_key="test-key", model="test-model")
        mock_resp = _mock_response(True, "Arm is visible")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                return await client.ask("Is the arm visible?", [b"fake_image"], {})

        result = asyncio.run(run())
        assert result["answer"] is True
        assert result["reason"] == "Arm is visible"

    def test_cost_tracking(self) -> None:
        client = VLMClient(api_key="test-key", model="test-model", cost_budget_usd=0.05)
        mock_resp = _mock_response(True, "ok", cost=0.02)

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                await client.ask("q1", [b"img"], {})
                assert client.cumulative_cost == pytest.approx(0.02)
                await client.ask("q2", [b"img"], {})
                assert client.cumulative_cost == pytest.approx(0.04)

        asyncio.run(run())

    def test_cost_budget_exceeded(self) -> None:
        client = VLMClient(api_key="test-key", model="test-model", cost_budget_usd=0.01)
        client._cumulative_cost = 0.02

        async def run():
            with pytest.raises(CostBudgetExceeded):
                await client.ask("q", [b"img"], {})

        asyncio.run(run())

    def test_false_answer(self) -> None:
        client = VLMClient(api_key="test-key", model="test-model")
        mock_resp = _mock_response(False, "Arm not visible")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                return await client.ask("Is the arm visible?", [b"fake_image"], {})

        result = asyncio.run(run())
        assert result["answer"] is False


class TestMakeVLMClient:
    def test_returns_none_without_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            # Make sure OPENROUTER_API_KEY is not set
            import os

            old = os.environ.pop("OPENROUTER_API_KEY", None)
            try:
                client = make_vlm_client()
                assert client is None
            finally:
                if old is not None:
                    os.environ["OPENROUTER_API_KEY"] = old

    def test_returns_client_with_api_key(self) -> None:
        import os

        old = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-123"
        try:
            client = make_vlm_client()
            assert client is not None
            assert client.api_key == "test-key-123"
        finally:
            if old is not None:
                os.environ["OPENROUTER_API_KEY"] = old
            else:
                os.environ.pop("OPENROUTER_API_KEY", None)
