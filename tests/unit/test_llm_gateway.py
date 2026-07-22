from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableLambda

from app.config.app_config import app_config
from app.llm.gateway import LLMGateway
from app.llm.model_router import ModelRoute
from app.llm.prompt_manager import PromptTemplateManager


class FakeRouter:
    def __init__(self, clients, *, fallback_model="fallback-model"):
        self.clients = clients
        self.primary_model = "primary-model"
        self.fallback_model = fallback_model
        self.created = []

    def route(self, *, fallback=False):
        return ModelRoute("fallback-model" if fallback else "primary-model", fallback_used=fallback)

    def create_client(self, model_name):
        self.created.append(model_name)
        client = self.clients[model_name]
        return client() if callable(client) and not hasattr(client, "invoke") else client


def prompt_manager(tmp_path):
    (tmp_path / "echo.prompt").write_text("hello {name}", encoding="utf-8")
    return PromptTemplateManager(prompt_dir=tmp_path, version="test")


@pytest.mark.asyncio
async def test_gateway_invokes_primary_model(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.llm, "max_retries", 0)
    router = FakeRouter({"primary-model": RunnableLambda(lambda payload: "ok")})
    gateway = LLMGateway(router=router, prompt_manager=prompt_manager(tmp_path))

    result = await gateway.ainvoke_text("echo", {"name": "world"})

    assert result == "ok"
    assert router.created == ["primary-model"]
    assert gateway.last_model_name == "primary-model"
    assert gateway.last_fallback_used is False


@pytest.mark.asyncio
async def test_gateway_retries_retryable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.llm, "max_retries", 2)
    attempts = {"count": 0}

    async def flaky(payload):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TimeoutError("timeout")
        return "ok"

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    router = FakeRouter({"primary-model": RunnableLambda(flaky)})
    gateway = LLMGateway(router=router, prompt_manager=prompt_manager(tmp_path), sleep=fake_sleep)

    result = await gateway.ainvoke_text("echo", {"name": "world"})

    assert result == "ok"
    assert attempts["count"] == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_gateway_falls_back_after_primary_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.llm, "max_retries", 0)
    router = FakeRouter(
        {
            "primary-model": RunnableLambda(lambda payload: (_ for _ in ()).throw(TimeoutError("timeout"))),
            "fallback-model": RunnableLambda(lambda payload: "fallback-ok"),
        }
    )
    gateway = LLMGateway(router=router, prompt_manager=prompt_manager(tmp_path))

    result = await gateway.ainvoke_text("echo", {"name": "world"})

    assert result == "fallback-ok"
    assert router.created == ["primary-model", "fallback-model"]
    assert gateway.last_model_name == "fallback-model"
    assert gateway.last_fallback_used is True


@pytest.mark.asyncio
async def test_gateway_streaming_records_output(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.llm, "max_retries", 0)
    router = FakeRouter({"primary-model": RunnableLambda(lambda payload: "stream-ok")})
    gateway = LLMGateway(router=router, prompt_manager=prompt_manager(tmp_path))

    chunks = [chunk async for chunk in gateway.astream_text("echo", {"name": "world"})]

    assert "".join(chunks) == "stream-ok"
    assert gateway.last_output_tokens > 0


@pytest.mark.asyncio
async def test_gateway_structured_output_uses_schema(tmp_path, monkeypatch):
    from pydantic import BaseModel

    class Result(BaseModel):
        value: str

    class Structured:
        async def ainvoke(self, payload):
            return {"value": payload["name"]}

    class Client:
        def with_structured_output(self, schema):
            assert schema is Result
            return Structured()

    monkeypatch.setattr(app_config.llm, "max_retries", 0)
    router = FakeRouter({"primary-model": Client()})
    gateway = LLMGateway(router=router, prompt_manager=prompt_manager(tmp_path))

    result = await gateway.ainvoke_structured("echo", {"name": "ok"}, Result)

    assert result == Result(value="ok")
