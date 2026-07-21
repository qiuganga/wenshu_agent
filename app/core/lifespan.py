import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import dw_mysql_client_manager, meta_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.config.app_config import validate_runtime_config
from app.service.query_service import admission_controller, request_dedup_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("APP_SKIP_RUNTIME_CONFIG_VALIDATION") != "1":
        validate_runtime_config()
    await admission_controller.reset()
    await request_dedup_registry.clear()
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    yield
    await admission_controller.begin_shutdown(timeout_seconds=5)
    await request_dedup_registry.clear()
    await qdrant_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await admission_controller.reset()
