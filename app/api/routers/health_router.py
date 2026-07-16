import asyncio

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import dw_mysql_client_manager, meta_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager

health_router = APIRouter()


@health_router.get("/health/live")
async def live():
    return {"status": "ok"}


async def _check_mysql(manager) -> bool:
    async with manager.session_factory() as session:
        await session.execute(text("select 1"))
    return True


async def _check_qdrant() -> bool:
    if qdrant_client_manager.client is None:
        return False
    await qdrant_client_manager.client.get_collections()
    return True


async def _check_es() -> bool:
    if es_client_manager.client is None:
        return False
    return bool(await es_client_manager.client.ping())


async def _check_embedding() -> bool:
    client = embedding_client_manager.client
    if client is None:
        return False
    async with httpx.AsyncClient(timeout=2, trust_env=False) as http_client:
        response = await http_client.post(f"{client.base_url}/embed", json={"inputs": ["health"]})
        response.raise_for_status()
    return True


@health_router.get("/health/ready")
async def ready():
    checks = {
        "meta_mysql": _check_mysql(meta_mysql_client_manager),
        "dw_mysql": _check_mysql(dw_mysql_client_manager),
        "qdrant": _check_qdrant(),
        "elasticsearch": _check_es(),
        "embedding": _check_embedding(),
    }
    results = {}
    for name, coro in checks.items():
        try:
            results[name] = await asyncio.wait_for(coro, timeout=3)
        except Exception:
            results[name] = False
    status = "ok" if all(results.values()) else "degraded"
    return {"status": status, "checks": results}
