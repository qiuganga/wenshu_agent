# 面试演示提纲

这份提纲用于 10 分钟内讲清楚 `wenshu-agent` 的核心设计。演示时重点讲工程边界，不要把 Demo 能力说成完整生产能力。

## 1. 30 秒项目介绍

这是一个 FastAPI + LangGraph 的后端 Agent 项目，目标是把自然语言分析问题转换为安全的只读 SQL，并通过 SSE 流式返回结果。

项目展示的重点不是“让大模型直接写 SQL”，而是：

- 元数据召回如何辅助 SQL 生成。
- SQL 如何经过安全网关。
- 查询如何限制行数、成本和超时。
- 结果如何脱敏后流式返回。
- 没有真实 LLM 和生产数据库时如何测试、评测和演示。

## 2. 1 分钟架构

主要入口：

- API：`app/api/routers/query_router.py`
- 服务层：`app/service/query_service.py`
- Graph：`app/agent/graph.py`
- State：`app/agent/state.py`
- SQL 安全：`app/security/sql_security.py`
- 成本评估：`app/security/sql_cost.py`
- 离线评测：`evals/run_evaluation.py`

完整链路：

```text
FastAPI
-> QueryService
-> LangGraph
-> metadata recall
-> SQL generation
-> SQL security validation
-> database validation
-> SQL cost evaluation
-> readonly execution
-> summary
-> SSE response
```

## 3. 2 分钟 LangGraph 流程

正常路径：

```text
START
-> extract_keywords
-> recall_column / recall_value / recall_metric
-> merge_retrieved_info
-> filter_table / filter_metric
-> add_extra_context
-> plan_query
-> generate_sql
-> security_validate_sql
-> database_validate_sql
-> evaluate_sql_cost
-> execute_sql
-> summarize_result
-> interpret_result
-> END
```

修正路径：

```text
validation failed
-> correct_sql
-> security_validate_sql
-> database_validate_sql
-> evaluate_sql_cost
```

讲解重点：

- `correct_sql` 后必须重新走安全、数据库和成本验证。
- `retry_count` 限制修正次数，避免 Agent 无限循环。
- `failed` 后不会执行 SQL。
- 测试通过 `AgentNodes` 注入 fake nodes，但仍复用生产图结构。

## 4. 2 分钟 SQL 安全

核心观点：Prompt 不是安全边界。

项目中的安全控制：

- 只允许单条 `SELECT` 或 `WITH ... SELECT`。
- 表和字段必须在白名单里。
- 默认禁止 `SELECT *`。
- 强制 `LIMIT` 并封顶。
- 禁止危险函数和 MySQL 危险能力。
- 动态 identifier 先校验再引用。
- SQL 成本过高时拒绝执行或进入修正。
- 数据库仍必须使用只读账号。

关键文件：

- `app/security/sql_security.py`
- `app/security/sql_identifiers.py`
- `app/security/sql_cost.py`
- `app/agent/nodes/security_validate_sql.py`
- `app/agent/nodes/evaluate_sql_cost.py`

## 5. 1 分钟 SSE 和取消

SSE 由 `app/service/query_service.py` 组织：

- 使用有界队列控制背压。
- 客户端断开后取消 graph task。
- 默认不返回完整 SQL 和原始行。
- `interpret_result` 会合并 token，减少过细粒度事件。

适合展示的点：

- 流式返回不是直接把所有内部数据推给前端。
- SSE payload 需要大小限制和脱敏。
- 断开连接后应停止后台消耗。

## 6. 1 分钟测试与评测

本地检查：

```powershell
uv run pytest -q
uv run pytest --cov=app --cov-report=term-missing
uv run mypy app/security app/agent app/service app/api app/core
uv run python -m evals.run_evaluation --smoke
```

说明：

- 默认测试不调用真实 LLM。
- 默认测试不连接生产数据库。
- 离线评测使用 fake LLM 和 Demo case。
- fake eval 只能证明回归链路，不证明真实模型准确率。

## 7. 1 分钟 Demo

启动命令：

```powershell
uv sync
Copy-Item conf\app_config.example.yaml conf\app_config.yaml
docker compose -f docker/docker-compose.yaml up -d
uv run python -m app.scripts.bootstrap_demo
uv run fastapi dev main.py
```

Linux/macOS：

```bash
uv sync
cp conf/app_config.example.yaml conf/app_config.yaml
docker compose -f docker/docker-compose.yaml up -d
uv run python -m app.scripts.bootstrap_demo
uv run fastapi dev main.py
```

## 8. 1 分钟技术难点和权衡

- SQL 安全不能只靠关键词，必须结合 AST、白名单和数据库权限。
- `LIMIT` 不能替代成本评估，因为 JOIN、排序和全表扫描仍可能很贵。
- `asyncio.wait_for` 只能限制应用等待时间，不等于杀掉数据库端查询。
- 离线 fake eval 很适合 CI，但不能替代真实模型验收。
- 元数据质量会影响字段权限判断，不能确定时应 fail-closed。

## 9. 常见追问

### 为什么 Prompt 不是安全边界？

因为模型输出不可控，攻击者可以诱导模型生成危险 SQL。安全规则必须在代码和数据库权限中执行。

### 为什么修正后的 SQL 必须重新验证？

修正也是一次新的模型输出，可能引入新的危险语法、越权表或高成本查询。

### 为什么 LIMIT 不能替代成本评估？

`LIMIT 10` 仍可能触发大表扫描、JOIN、filesort 或临时表，数据库需要先计算很多中间结果。

### asyncio.wait_for 是否会杀掉 MySQL 查询？

不会保证杀掉数据库端正在执行的查询。它主要限制应用层等待时间，所以仍需要数据库账号权限、只读事务和执行超时配合。

### 为什么需要只读数据库账号？

应用层校验可能存在 bug，只读账号是数据库层的最终权限边界。

### LangGraph 和普通 if/else 有什么区别？

LangGraph 把节点、状态、条件边和并行分支显式建模，便于测试、观测和复用生产流程。

### 如何处理客户端断开？

`QueryService` 监听断开事件，取消 graph task，并停止继续发送 SSE。

### fake eval 为什么不能证明真实模型效果？

fake eval 检查的是工程链路和回归指标，不覆盖真实模型的泛化能力、幻觉和供应商差异。

### 字段白名单依赖错误元数据怎么办？

元数据不确定时采用 fail-closed，拒绝执行并返回脱敏错误。

### 如何避免 Agent 无限修正？

使用 `retry_count` 和配置上限，超过次数进入 `failed` 节点。

## 10. 回答要点

- 先强调安全边界在代码和数据库，不在 Prompt。
- 再说明 Graph 中每次修正都会重新验证。
- 展示测试和 CI 可以在无真实 LLM 环境下运行。
- 最后诚实说明限制：成本评估是估算，Demo bootstrap 不是完整生产灌库，Trace 仍是轻量接入。
