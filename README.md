# data-agent

FastAPI + LangGraph data analysis agent.

## Setup

1. Install dependencies with uv:

```powershell
uv sync
```

2. Create local config:

```powershell
Copy-Item conf\app_config.example.yaml conf\app_config.yaml
```

3. Edit `conf/app_config.yaml` and fill in your own LLM API key:

```yaml
llm:
  api_key: your_siliconflow_api_key_here
```

4. Start backend:

```powershell
uv run fastapi dev main.py
```

The real `conf/app_config.yaml` is intentionally ignored by Git to avoid committing secrets.

## Notes

The embedding model weight file `docker/embedding/**/pytorch_model.bin` is ignored because it is too large for normal GitHub commits. Prepare it locally before starting the Docker embedding service.
