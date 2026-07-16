from fastapi import APIRouter, Request
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QueryRequest
from app.service.query_service import QueryService

query_router = APIRouter()


def _streaming_response(generator):
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@query_router.post("/api/v1/query")
async def query_v1(
    query: QueryRequest,
    request: Request,
    query_service: QueryService = Depends(get_query_service),
):
    return _streaming_response(query_service.query(query, request))


@query_router.post("/api/query", deprecated=True)
async def query_legacy(
    query: QueryRequest,
    request: Request,
    query_service: QueryService = Depends(get_query_service),
):
    return _streaming_response(query_service.query(query, request))
