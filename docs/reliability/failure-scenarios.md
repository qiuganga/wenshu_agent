# Failure Scenarios

## Redis

- Scenario: Redis restart or connection failure.
- Detection: `/health/ready` reports `redis=false`, cache/dedup/admission spans show Redis errors.
- Recovery: application falls back where supported, rejects unsafe lifecycle operations with stable error codes, and reconnects through the Redis client manager on restart.

## MySQL

- Scenario: metadata or DW database unavailable.
- Detection: `/health/ready` reports `meta_mysql=false` or `dw_mysql=false`; query execution returns sanitized error responses.
- Recovery: restore database connectivity, verify read-only user permissions, and check audit logs by `error_code`.

## Qdrant

- Scenario: vector database unavailable.
- Detection: `/health/ready` reports `qdrant=false`; semantic cache and metadata recall degrade to miss/failure without exposing payloads.
- Recovery: restart Qdrant, verify collection health, and rebuild metadata if collection integrity is affected.

## LLM

- Scenario: timeout or rate limit.
- Detection: LLM gateway records retry/fallback attributes and query result falls back only where deterministic fallback is safe.
- Recovery: verify provider status, fallback model configuration, and timeout settings.

## Application Worker

- Scenario: worker crash during graph execution.
- Detection: missing terminal audit plus running checkpoint.
- Recovery: next request with the same `execution_id` resumes from checkpoint where possible; completed nodes are not re-executed.

## Shutdown Drill

- Scenario: deploy rolling restart.
- Detection: new requests receive `SERVICE_SHUTTING_DOWN`, active graph tasks drain until `server.shutdown_timeout_seconds`.
- Recovery: Kubernetes readiness removes terminating pods before traffic is sent to replacements.
