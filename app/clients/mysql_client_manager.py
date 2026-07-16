import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.app_config import DBConfig, app_config


class MysqlClientManager:
    def __init__(self, db_config: DBConfig):
        self.db_config = db_config
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    def _get_url(self):
        return (
            f"mysql+asyncmy://{self.db_config.user}:{self.db_config.password}"
            f"@{self.db_config.host}:{self.db_config.port}/{self.db_config.database}?charset=utf8mb4"
        )

    def init(self):
        self.engine = create_async_engine(url=self._get_url(), pool_size=10, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=True,
            expire_on_commit=False,
            autobegin=True,
        )

    async def close(self):
        if self.engine is not None:
            await self.engine.dispose()


dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)


if __name__ == "__main__":
    meta_mysql_client_manager.init()

    async def test():
        assert meta_mysql_client_manager.session_factory is not None
        async with meta_mysql_client_manager.session_factory() as session:
            result = await session.execute(text("select 1"))
            print(result.scalar())

    asyncio.run(test())
