import asyncio

from elasticsearch import AsyncElasticsearch

from app.config.app_config import ESConfig, app_config


class ESClientManager:
    def __init__(self, config: ESConfig):
        self.config = config
        self.client: AsyncElasticsearch | None = None

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        self.client = AsyncElasticsearch(hosts=[self._get_url()])

    async def close(self):
        if self.client:
            await self.client.close()


es_client_manager = ESClientManager(app_config.es)


async def create_index_with_mapping():
    es_client_manager.init()

    try:
        client = es_client_manager.client
        index_name = app_config.es.index_name

        exists = await client.indices.exists(index=index_name)

        if exists:
            print(f"索引 {index_name} 已存在，不重复创建")
        else:
            mappings = {
                "properties": {
                    "id": {
                        "type": "keyword"
                    },
                    "doc_type": {
                        "type": "keyword"
                    },
                    "database": {
                        "type": "keyword"
                    },
                    "table_id": {
                        "type": "keyword"
                    },
                    "table_name": {
                        "type": "keyword"
                    },
                    "column_id": {
                        "type": "keyword"
                    },
                    "column_name": {
                        "type": "keyword"
                    },
                    "name": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart",
                        "fields": {
                            "keyword": {
                                "type": "keyword",
                                "ignore_above": 256
                            }
                        }
                    },
                    "description": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart"
                    },
                    "alias": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart"
                    },
                    "examples": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart"
                    }
                }
            }

            settings = {
                "number_of_shards": 1,
                "number_of_replicas": 0
            }

            await client.indices.create(
                index=index_name,
                settings=settings,
                mappings=mappings
            )

            print(f"索引 {index_name} 创建成功")

        # 查看 mapping
        mapping_result = await client.indices.get_mapping(index=index_name)
        print("当前 mapping:")
        print(mapping_result[index_name]["mappings"])

        # 写入一条测试文档
        test_doc = {
            "id": "table_fact_order",
            "doc_type": "table",
            "database": "dw",
            "table_id": "fact_order",
            "table_name": "fact_order",
            "name": "订单事实表",
            "description": "记录订单金额、订单数量、客户、商品、地区、日期等订单明细信息",
            "alias": "订单表 销售明细表 交易事实表",
            "examples": "order_amount 表示订单金额，order_quantity 表示订单数量"
        }

        await client.index(
            index=index_name,
            id=test_doc["id"],
            document=test_doc
        )

        await client.indices.refresh(index=index_name)

        print("测试文档写入成功")

        # 查询测试
        search_result = await client.search(
            index=index_name,
            query={
                "multi_match": {
                    "query": "订单金额",
                    "fields": [
                        "name^3",
                        "description^2",
                        "alias",
                        "examples"
                    ]
                }
            }
        )

        print("搜索结果:")
        for hit in search_result["hits"]["hits"]:
            print("score:", hit["_score"])
            print("source:", hit["_source"])

    finally:
        await es_client_manager.close()


if __name__ == '__main__':
    asyncio.run(create_index_with_mapping())