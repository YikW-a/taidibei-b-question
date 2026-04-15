from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuestionRecord:
    question_id: str
    question_type: str
    original_question_json: str
    raw_question: str
    sub_questions: list[str]


@dataclass
class ParsedIntent:
    intent_type: str
    companies: list[str] = field(default_factory=list)
    stock_codes: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    top_n: int | None = None
    threshold: float | None = None
    chart_type: str | None = None
    notes: list[str] = field(default_factory=list)


__all__ = ["ParsedIntent", "QuestionRecord"]
