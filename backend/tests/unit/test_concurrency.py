"""Regression: slow LLM work in one request must not stall every other request.

Endpoints used to be `async def` while calling Gemini/DB synchronously (with
time.sleep in retries), which blocked the event loop: with one uvicorn worker,
a single slow chat froze the whole API. Blocking endpoints are now plain `def`
(run in FastAPI's threadpool) and the SSE generator is synchronous.
"""

import asyncio
import time
from unittest.mock import patch

import httpx
import pytest

SLOW_SECONDS = 1.5
REFLECTION = {"confidence": 0.9, "scores": {}, "feedback": "ok", "should_retry": False}


def _slow_before_stream(**kwargs):
    time.sleep(SLOW_SECONDS)  # classify + retrieve + rerank before the first token
    return iter(["ok"]), [], {}


def _slow_during_stream(**kwargs):
    def tokens():
        time.sleep(SLOW_SECONDS)  # Gemini streaming
        yield "ok"
    return tokens(), [], {}


@pytest.mark.parametrize("slow_ask", [_slow_before_stream, _slow_during_stream],
                         ids=["before_stream", "during_stream"])
async def test_slow_chat_does_not_block_other_requests(client, auth_headers, monkeypatch, slow_ask):
    from src.main import app

    monkeypatch.setattr("src.api.router_chat.settings.agent_mode", "simple")

    with patch("src.rag.graph_rag.ask", side_effect=slow_ask), \
         patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            t0 = time.perf_counter()

            async def finished_at(coro):
                res = await coro
                return res, time.perf_counter() - t0

            chat_task = asyncio.create_task(
                finished_at(ac.post("/api/v1/chat", json={"message": "Câu hỏi chậm"}, headers=auth_headers))
            )
            await asyncio.sleep(0.2)  # let the chat request reach the slow part
            me, me_done = await finished_at(ac.get("/api/v1/auth/me", headers=auth_headers))
            chat, chat_done = await chat_task

    assert chat.status_code == 200
    assert me.status_code == 200
    assert chat_done >= SLOW_SECONDS
    # Blocked loop => /me could only finish after the chat (~1.5 s). Free loop => ~0.2 s.
    assert me_done < SLOW_SECONDS - 0.5, f"/auth/me waited {me_done:.2f}s for the slow chat"
