from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptRisk:
    allowed: bool
    risk_level: str
    score: int
    reasons: list[str]


class PromptInjectionGuard:
    PATTERNS = (
        (re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE), 60, "ignore_previous"),
        (re.compile(r"system\s+prompt", re.IGNORECASE), 50, "system_prompt_request"),
        (
            re.compile(r"(reveal|print|output|show).{0,40}(secret|api[_ -]?key|token|password)", re.IGNORECASE),
            80,
            "secret_request",
        ),
        (re.compile(r"(call|execute|run).{0,40}(tool|function)", re.IGNORECASE), 40, "tool_instruction"),
        (
            re.compile(r"(override|replace).{0,40}(system|developer).{0,20}instruction", re.IGNORECASE),
            70,
            "instruction_override",
        ),
    )

    def check(self, text: str) -> PromptRisk:
        reasons: list[str] = []
        score = 0
        for pattern, weight, reason in self.PATTERNS:
            if pattern.search(text):
                score += weight
                reasons.append(reason)
        if score >= 80:
            return PromptRisk(False, "HIGH", score, reasons)
        if score >= 60:
            return PromptRisk(False, "MEDIUM", score, reasons)
        if score > 0:
            return PromptRisk(True, "LOW", score, reasons)
        return PromptRisk(True, "LOW", 0, [])


prompt_injection_guard = PromptInjectionGuard()
