from __future__ import annotations

from dataclasses import dataclass

from app.security.context import SecurityContext
from app.security.prompt_guard import PromptInjectionGuard, prompt_injection_guard


@dataclass(frozen=True)
class DocumentTrustLevel:
    source: str
    trust_level: str
    verified: bool


@dataclass(frozen=True)
class DocumentSecurityDecision:
    allowed: bool
    reason: str
    risk_level: str = "LOW"


class RAGSecurityGuard:
    def __init__(self, prompt_guard: PromptInjectionGuard | None = None) -> None:
        self.prompt_guard = prompt_guard or prompt_injection_guard

    def check(self, context: SecurityContext, document: str, trust: DocumentTrustLevel) -> DocumentSecurityDecision:
        del context
        normalized_trust = trust.trust_level.upper()
        if not trust.verified and normalized_trust in {"LOW", "UNTRUSTED"}:
            return DocumentSecurityDecision(False, "untrusted_document", "HIGH")
        prompt_risk = self.prompt_guard.check(document)
        if not prompt_risk.allowed:
            return DocumentSecurityDecision(False, "document_prompt_injection", prompt_risk.risk_level)
        return DocumentSecurityDecision(True, "trusted_document", prompt_risk.risk_level)


rag_security_guard = RAGSecurityGuard()
