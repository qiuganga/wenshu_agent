from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

from app.config.app_config import app_config
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.repository.qdrant.base_qdrant_repository import BaseQdrantRepository


class ColumnQdrantRepository(BaseQdrantRepository[ColumnInfoQdrant]):
    collection_name: str = 'data-agent-column'

