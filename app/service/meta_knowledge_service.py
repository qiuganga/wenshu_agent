import uuid
from pathlib import Path

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.config.config_loader import load_config
from app.config.meta_config import MetaConfig
from app.core.logging import logger
from app.models.es.value_info_es import ValueInfoES
from app.models.mysql.column_info_mysql import ColumnInfoMySQL
from app.models.mysql.column_metric_mysql import ColumnMetricMySQL
from app.models.mysql.metric_info_mysql import MetricInfoMySQL
from app.models.mysql.table_info_mysql import TableInfoMySQL
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant
from app.repository.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repository.mysql.dw_mysql_repository import DWMySQLRepository
from app.repository.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repository.es.value_es_repository import ValueESRepository
from app.repository.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    def __init__(self, meta_mysql_repository: MetaMySQLRepository,
                 dw_mysql_repository: DWMySQLRepository,
                 column_qdrant_repository: ColumnQdrantRepository,
                 embedding_client: HuggingFaceEndpointEmbeddings,
                 value_es_repository: ValueESRepository,
                 metric_qdrant_repository: MetricQdrantRepository):
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.column_qdrant_repository = column_qdrant_repository
        self.embedding_client = embedding_client
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository

    def _convert_column_info_from_mysql_to_qdrant(self, column_info: ColumnInfoMySQL) -> ColumnInfoQdrant:
        return ColumnInfoQdrant(
            id=column_info.id,
            name=column_info.name,
            type=column_info.type,
            role=column_info.role,
            examples=column_info.examples,
            description=column_info.description,
            alias=column_info.alias,
            table_id=column_info.table_id
        )

    async def _save_tables_to_meta_db(self, meta_config: MetaConfig):

        table_infos: list[TableInfoMySQL] = []
        column_infos: list[ColumnInfoMySQL] = []

        for table in meta_config.tables:
            # table->TableInfoMySQL
            table_info = TableInfoMySQL(
                id=table.name,
                name=table.name,
                role=table.role,
                description=table.description
            )
            table_infos.append(table_info)

            # 查询该表的所有字段类型
            column_types: dict[str, str] = await self.dw_mysql_repository.get_column_types(table.name)
            for column in table.columns:
                column_values: list = await self.dw_mysql_repository.get_column_values(table.name, column.name, 10)
                # column->ColumnInfoMySQL
                column_info = ColumnInfoMySQL(
                    id=f"{table.name}.{column.name}",
                    name=column.name,
                    type=column_types[column.name],
                    role=column.role,
                    examples=column_values,
                    description=column.description,
                    alias=column.alias,
                    table_id=table.name
                )
                column_infos.append(column_info)

        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_table_infos(table_infos)
            await self.meta_mysql_repository.save_column_infos(column_infos)

        return table_infos, column_infos

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfoMySQL]):
        await self.column_qdrant_repository.ensure_collection()
        points: list[dict] = []
        for column_info in column_infos:
            points.append({
                'id': uuid.uuid4(),
                'embedding_text': column_info.name,
                'payload': self._convert_column_info_from_mysql_to_qdrant(column_info)
            })
            points.append({
                'id': uuid.uuid4(),
                'embedding_text': column_info.description,
                'payload': self._convert_column_info_from_mysql_to_qdrant(column_info)
            })
            for alia in column_info.alias:
                points.append({
                    'id': uuid.uuid4(),
                    'embedding_text': alia,
                    'payload': self._convert_column_info_from_mysql_to_qdrant(column_info)
                })
        # 向量列表
        embedding_texts = [point['embedding_text'] for point in points]
        embedding_batch_size = 10
        embeddings = []
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i:i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_texts)
            embeddings.extend(batch_embeddings)

        # id列表
        ids = [point['id'] for point in points]

        # payload列表
        payloads = [point['payload'] for point in points]

        await self.column_qdrant_repository.upsert(ids, embeddings, payloads)

    async def _save_value_info_to_es(self, meta_config: MetaConfig, column_infos: list[ColumnInfoMySQL]):
        # 取保index存在
        await self.value_es_repository.ensure_index()
        column2sync: dict[str, bool] = {}
        for table in meta_config.tables:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = column.sync

        value_infos: list[ValueInfoES] = []
        for column_info in column_infos:
            sync = column2sync[column_info.id]
            if sync:
                # 查询这个列的所有取值
                table_name = column_info.table_id
                column_name = column_info.name
                values = await self.dw_mysql_repository.get_column_values(table_name, column_name, 100000)
                current_value_infos = [ValueInfoES(id=f"{column_info.id}.{value}",
                                                   value=value,
                                                   type=column_info.type,
                                                   column_id=column_info.id,
                                                   column_name=column_info.name,
                                                   table_id=column_info.table_id,
                                                   table_name=column_info.table_id
                                                   ) for value in values]
                value_infos.extend(current_value_infos)
        await self.value_es_repository.index(value_infos)

    async def _save_metrics_to_meta_db(self, meta_config):
        metric_infos: list[MetricInfoMySQL] = []
        column_metrics: list[ColumnMetricMySQL] = []
        for metric in meta_config.metrics:
            # 构造MetricInfoMySQL数据
            metric_info = MetricInfoMySQL(id=metric.name,
                                          name=metric.name,
                                          description=metric.description,
                                          relevant_columns=metric.relevant_columns,
                                          alias=metric.alias)
            metric_infos.append(metric_info)

            for relevant_column in metric.relevant_columns:
                # 构造ColumnMetricMySQL数据
                column_metric = ColumnMetricMySQL(column_id=relevant_column, metric_id=metric.name)
                column_metrics.append(column_metric)

        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_metric_infos(metric_infos)
            await self.meta_mysql_repository.save_column_metrics(column_metrics)

        return metric_infos

    def _convert_metric_info_from_mysql_to_qdrant(self, metric_info: MetricInfoMySQL) -> MetricInfoQdrant:
        return MetricInfoQdrant(id=metric_info.id,
                                name=metric_info.name,
                                description=metric_info.description,
                                relevant_columns=metric_info.relevant_columns,
                                alias=metric_info.alias)

    async def _save_metric_info_to_qdrant(self, metric_infos):
        points: list[dict] = []
        for metric_info in metric_infos:
            points.append({
                'id': uuid.uuid4(),
                'embedding_text': metric_info.name,
                'payload': self._convert_metric_info_from_mysql_to_qdrant(metric_info)
            })
            points.append({
                'id': uuid.uuid4(),
                'embedding_text': metric_info.description,
                'payload': self._convert_metric_info_from_mysql_to_qdrant(metric_info)
            })
            for alia in metric_info.alias:
                points.append({
                    'id': uuid.uuid4(),
                    'embedding_text': alia,
                    'payload': self._convert_metric_info_from_mysql_to_qdrant(metric_info)
                })

        ids = [point['id'] for point in points]
        embeddings = []
        embedding_texts = [point['embedding_text'] for point in points]
        embedding_batch_size = 10
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i:i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_texts)
            embeddings.extend(batch_embeddings)
        payloads = [point['payload'] for point in points]

        # 确保collection存在
        await self.metric_qdrant_repository.ensure_collection()
        # 保存数据到qdrant
        await self.metric_qdrant_repository.upsert(ids, embeddings, payloads)

    async def build(self, config_path: Path):
        # 1.加载配置文件
        meta_config: MetaConfig = load_config(config_path, MetaConfig)
        logger.info("加载配置文件")
        # 2.处理表信息
        if meta_config.tables:
            # 2.1 保存表信息到meta数据库
            table_infos, column_infos = await self._save_tables_to_meta_db(meta_config)
            logger.info("保存表信息到meta数据库")

            # 2.2 为字段信息建立向量索引
            await self._save_column_info_to_qdrant(column_infos)
            logger.info("为字段信息建立向量索引")

            # 2.3 为字段取值建立全文索引
            await self._save_value_info_to_es(meta_config, column_infos)
            logger.info("为字段取值建立全文索引")

        # 3.处理指标信息
        if meta_config.metrics:
            # 3.1 保存指标信息到meta数据库
            metric_infos = await self._save_metrics_to_meta_db(meta_config)
            logger.info("保存指标信息到meta数据库")

            # 3.2 为指标信息建立向量索引
            await self._save_metric_info_to_qdrant(metric_infos)
            logger.info("为指标信息建立向量索引")

        logger.info("元数据知识库构建完成")
