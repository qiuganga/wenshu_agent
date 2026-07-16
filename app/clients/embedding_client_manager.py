
import httpx

from app.config.app_config import EmbeddingConfig, app_config


class LocalEndpointEmbeddings:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _prepare_texts(texts: list[str]) -> list[str]:
        return [text.replace("\n", " ") for text in texts]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embed",
            json={"inputs": self._prepare_texts(texts)},
            timeout=60,
            trust_env=False,
        )
        response.raise_for_status()
        return response.json()

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/embed",
                json={"inputs": self._prepare_texts(texts)},
            )
        response.raise_for_status()
        return response.json()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.client: LocalEndpointEmbeddings | None = None
        self.config = config

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        self.client = LocalEndpointEmbeddings(base_url=self._get_url())


embedding_client_manager = EmbeddingClientManager(app_config.embedding)
