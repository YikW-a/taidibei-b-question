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
    sort_desc: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class QuestionResult:
    question_id: str
    question_type: str
    original_question_json: str
    raw_question: str
    intent_type: str
    parsed_companies: str
    parsed_periods: str
    parsed_metrics: str
    generated_query: str
    answer_text: str
    answer_json: str
    result_preview: str
    chart_path: str
    graph_format: str
    status: str
    query_attempts: int
    note: str
