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
class ParsedTask3Intent:
    intent_type: str
    companies: list[str] = field(default_factory=list)
    stock_codes: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    focus_topics: list[str] = field(default_factory=list)
    needs_sql: bool = False
    needs_retrieval: bool = True
    top_n: int | None = None
    threshold: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RetrievedEvidence:
    source_type: str
    title: str
    relative_path: str
    publish_date: str = ""
    company_or_industry: str = ""
    organization: str = ""
    snippet: str = ""
    score: float = 0.0


__all__ = ["ParsedTask3Intent", "QuestionRecord", "RetrievedEvidence"]

