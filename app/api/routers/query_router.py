import asyncio
from typing import Annotated

from fastapi import APIRouter
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QuerySchema
from app.service.query_service import QueryService

query_router = APIRouter()


async def fake_video_streamer():
    for i in range(10):
        await asyncio.sleep(1)
        yield f"data: stage-{i}\n\n"


@query_router.post("/api/query")
async def query(query: QuerySchema, query_service: QueryService = Depends(get_query_service)):
    return StreamingResponse(query_service.query(query.query), media_type="text/event-stream")
