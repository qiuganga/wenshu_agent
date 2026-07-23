# Hybrid Candidate Ranking

This document describes the table and metric filtering upgrade. The goal is to reduce candidate scope with
deterministic scoring before asking the LLM to rerank a constrained safe candidate list.

## Flow

Existing flow:

1. recall columns, values, and metrics
2. merge metadata
3. send candidates directly to the LLM
4. keep allowlisted LLM selections

New flow:

1. recall columns, values, and metrics
2. preserve safe vector similarity scores when repositories expose them
3. extract deterministic query requirements from existing state
4. score table and metric candidates
5. compute deterministic top-k and greedy requirement coverage
6. send only safe summaries to the LLM for constrained reranking
7. validate LLM output against deterministic candidates
8. fall back to deterministic ranking on timeout, parse failure, or provider failure

## Retrieval Scores

`search()` remains backward compatible and returns payloads only. `search_with_scores()` returns
`ScoredCandidate[payload]` with a normalized score in `[0, 1]`. Missing, NaN, and Infinity scores become `0`; the code
does not invent a high similarity score. The score is treated as similarity only because the current Qdrant collection
uses cosine distance in collection creation.

Embedding vectors are never written to State, checkpoints, logs, telemetry, or SSE.

## Deterministic Features

Table scoring uses:

- table name and description matches
- column name, alias, and description matches
- vector similarity
- field requirement coverage
- value column matches
- metric column support
- role and relationship hints

Metric scoring uses:

- metric name, alias, and description matches
- vector similarity
- relevant column coverage
- selected table support

All scores are deterministic and use configured weights. Ties are sorted by total score, coverage, vector similarity,
and candidate name.

## Relationship Limits

`TableRelationshipGraph` supports confirmed relationships only. Same-named columns are not treated as confirmed
foreign keys. If no relationship metadata is available, ranking safely degrades instead of fabricating join paths.
Bridge tables must come from the confirmed relationship graph and still need downstream ACL and SQL validation.

## LLM Reranking

The LLM receives only safe summaries:

- candidate names
- role
- score bucket
- covered requirement count
- relationship summary
- reason codes

It does not receive raw retrieval payloads, sample values, ACL internals, user identity, tenant identity, embeddings,
SQL, or prompt history. The LLM can only reorder and select names from the deterministic top-k candidate list. Unknown
names, duplicates, and excessive selections are removed by code.

If reranking fails, the flow continues with `deterministic_fallback`.

## ACL Boundary

Ranking only decides relevance. It does not grant permission and does not replace SQL ACL, whitelist, or
`security_validate_sql`. The distinction is:

- `RELEVANCE_SELECTED`: ranking selected a candidate
- `PERMISSION_ALLOWED`: authorization allowed access
- `SQL_WHITELIST_ALLOWED`: final SQL validation allowed execution

These are separate controls.

## Current Limitations

- Relationship graph quality depends on real metadata availability.
- The current graph still keeps table and metric filter nodes structurally compatible with the existing flow.
- Metric selected-table support is best-effort because `filter_table` and `filter_metric` remain independent nodes in
  the existing LangGraph topology.
