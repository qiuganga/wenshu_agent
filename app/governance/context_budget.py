from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextBudgetPolicy:
    max_history_messages: int = 8
    max_documents: int = 5
    max_document_chars: int = 2000
    max_output_tokens: int = 1024
    max_agent_steps: int = 20
    max_handoffs: int = 5

    def trim_documents(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trimmed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for document in documents:
            text = str(document.get("content", ""))
            key = text[:200]
            if key in seen:
                continue
            seen.add(key)
            safe_document = {key: value for key, value in document.items() if key != "raw_result"}
            safe_document["content"] = text[: self.max_document_chars]
            trimmed.append(safe_document)
            if len(trimmed) >= self.max_documents:
                break
        return trimmed

    def trim_history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        safe = []
        for message in messages[-self.max_history_messages :]:
            role = str(message.get("role", "user"))
            content = str(message.get("content", ""))
            safe.append({"role": role, "content": content[: self.max_document_chars]})
        return safe
