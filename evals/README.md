# Offline Evaluation

This directory contains a lightweight fake evaluation suite for CI and interview demos. It does not call a real LLM and does not connect to production databases.

Run smoke cases:

```powershell
uv run python -m evals.run_evaluation --smoke
```

Run all demo cases:

```powershell
uv run python -m evals.run_evaluation
```

The metrics are regression signals for this demo project, not proof of absolute model correctness.
