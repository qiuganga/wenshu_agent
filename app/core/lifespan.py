import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import dw_mysql_client_manager, meta_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.config.app_config import app_config, validate_runtime_config
from app.core.shutdown import ShutdownManager
from app.core.telemetry import telemetry_manager
from app.service.query_service import admission_controller, request_dedup_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_started = time.perf_counter()
    if os.getenv("APP_SKIP_RUNTIME_CONFIG_VALIDATION") != "1":
        validate_runtime_config()
    telemetry_manager.init()
    telemetry_manager.increment_counter("startup_total")
    redis_client_manager.init()
    await admission_controller.reset()
    await request_dedup_registry.clear()
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    telemetry_manager.record_histogram("startup_time_seconds", time.perf_counter() - startup_started)
    yield
    shutdown_manager = ShutdownManager(timeout_seconds=app_config.server.shutdown_timeout_seconds)

    async def stop_accepting():
        await admission_controller.begin_shutdown(timeout_seconds=app_config.server.shutdown_timeout_seconds)

    await shutdown_manager.run(
        stop_accepting=stop_accepting,
        cleanup_steps=[
            request_dedup_registry.clear,
            qdrant_client_manager.close,
            es_client_manager.close,
            redis_client_manager.close,
            meta_mysql_client_manager.close,
            dw_mysql_client_manager.close,
            telemetry_manager.shutdown,
            admission_controller.reset,
        ],
    )
