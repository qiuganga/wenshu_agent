# Cost, SLO, and Scaling Governance

This phase adds deterministic governance primitives for production operation. The modules live under
`app/governance` and are designed to reuse existing Redis, telemetry, LLM gateway, cache, security context,
evaluation, and multi-agent infrastructure.

## Budget Governance

`BudgetContext` stores only safe identifiers and counters:

- request and execution identifiers
- hashed user and tenant scopes
- token, cost, step, LLM call, handoff, and runtime limits
- consumed counters and policy version

It must not store prompt text, response text, raw SQL, raw results, API keys, user ids, or tenant ids.

`TokenBudgetManager` reserves estimated input/output tokens before LLM calls and settles actual or estimated usage
after the call. Retry, fallback, and handoff usage are part of the same execution budget. A resumed execution should
reuse its existing budget context instead of creating a second full reservation.

`CostBudgetManager` tracks cost reservations in minor currency units and supports idempotent settlement ids. If model
execution succeeds but settlement fails, the request can be marked `COST_SETTLEMENT_PENDING` and retried with the same
settlement id.

## Pricing Catalog

`PricingCatalog` is versioned and configuration-backed. Unknown pricing fails safe by default. A non-strict mode may
mark cost as `cost_unknown`, but must not treat unknown pricing as zero-cost production usage. Example pricing in
configuration is a disabled placeholder; production deployments must maintain real pricing versions separately.

## Quota

`QuotaManager` enforces global, tenant, and user scopes with hashed keys. The stricter matching rule wins. Redis-backed
production implementations should use atomic Lua or transactions. Local fallback is for deterministic unit tests and
single-instance development only.

## Adaptive Routing

`AdaptiveModelRouter` chooses models based on request complexity, remaining token budget, remaining cost budget, model
health TTL, required capabilities, structured-output needs, and context-window requirements. It never routes to a model
that lacks required capabilities just because it is cheaper.

## SLO and Error Budget

`SLOManager` keeps a bounded sliding window and separates business or security denials from system failures. Timeouts
and internal failures count against SLO. `ErrorBudgetManager` reports `HEALTHY`, `WARNING`, or `EXHAUSTED` with
hysteresis through a recovery threshold. Single-process in-memory SLO accounting is not a global multi-instance SLO.

## Load Shedding and Degradation

`LoadSheddingController` protects health checks, recovery requests, and cache hits. It rejects low-priority heavy work
under overload with `SERVICE_OVERLOADED` and a retry-after hint. It does not interrupt requests after unsafe side
effects have started.

`DegradationPolicy` allows optional dependencies such as telemetry and evaluation to degrade safely, while budget,
quota, and authorization controls fail closed.

## FinOps Reporting

`FinOpsAggregator` aggregates by safe dimensions: time bucket, tenant hash, model, agent, cache hit, usage source, and
pricing version. It separates estimated cost, provider-reported cost, and avoided cache savings. It never aggregates by
raw query, prompt, response, SQL, raw result, user id, or tenant id.

## Capacity

`CapacityPlanner` emits estimated instance capacity, recommended replicas, saturation ratio, and scaling reasons. These
are advisory scaling signals. Kubernetes HPA cannot directly read OpenTelemetry metrics without a custom metrics
adapter, so this phase does not add unusable custom-metric HPA rules.
