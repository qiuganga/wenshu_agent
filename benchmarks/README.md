# Runtime Benchmarks

This directory contains local load-test scaffolding for the SSE query API.

Run only against an isolated test environment:

```bash
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8000
```

Scenarios:

- cache hit
- cache miss
- slow LLM
- admission concurrency
- timeout

Record QPS, latency, P50/P95/P99, and error rate. Do not point these tests at production data or production Redis/Qdrant namespaces.
