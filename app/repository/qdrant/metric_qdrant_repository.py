from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

from app.config.app_config import app_config
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant
from app.repository.qdrant.base_qdrant_repository import BaseQdrantRepository


class MetricQdrantRepository(BaseQdrantRepository[MetricInfoQdrant]):
    collection_name = 'data-agent-metric'

