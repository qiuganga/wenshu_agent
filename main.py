import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routers.health_router import health_router
from app.api.routers.query_router import query_router
from app.core.context import request_id_ctx_var
from app.core.exceptions import AppException, sanitize_exception
from app.core.lifespan import lifespan
from app.core.logging import logger

REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")

app = FastAPI(title="wenshu-agent", lifespan=lifespan)
app.include_router(query_router)
app.include_router(health_router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    incoming_request_id = request.headers.get("X-Request-ID")
    request_id = (
        incoming_request_id
        if incoming_request_id and REQUEST_ID_RE.match(incoming_request_id)
        else str(uuid.uuid4())
    )
    token = request_id_ctx_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_ctx_var.reset(token)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    logger.warning(f"app exception code={exc.code} path={request.url.path}")
    return JSONResponse(status_code=exc.status_code, content=exc.to_response())


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"unhandled exception path={request.url.path}: {exc}")
    app_exc = sanitize_exception(exc)
    return JSONResponse(status_code=500, content=app_exc.to_response())
