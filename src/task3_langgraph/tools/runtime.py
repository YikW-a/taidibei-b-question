from __future__ import annotations

import json
import re
import sqlite3
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine

from ..config import Task3LangGraphConfig
from ..schemas import QuestionRecord
from ..services import (
    OpenAICompatibleClient,
    OpenAICompatibleEmbeddingClient,
    OpenAICompatibleRerankerClient,
    PromptManager,
    Task3IntentParser,
    extract_json_object,
    load_questions,
)
from .report_parser import build_report_chunk_manifest
from .report_metadata import build_report_metadata_lookup, load_field_descriptions
from .retrieval import HybridRetriever, MetadataRetriever, VectorRetriever
from .vector_store import VectorStoreManager


SAFE_SQL_PREFIXES = ("select", "with")
FORBIDDEN_SQL_TOKENS = ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "attach ", "pragma ")
DERIVABLE_SINGLE_QUARTER_COLUMNS = [
    "total_operating_revenue",
    "net_profit",
    "total_profit",
    "operating_expense_rnd_expenses",
    "operating_expense_selling_expenses",
    "operating_expense_cost_of_sales",
    "operating_expense_administrative_expenses",
    "operating_expense_financial_expenses",
    "operating_expense_taxes_and_surcharges",
    "total_operating_expenses",
    "operating_cf_net_amount",
    "investing_cf_net_amount",
    "financing_cf_net_amount",
    "net_profit_excl_non_recurring",
]
PERIOD_ORDER = {"Q1": 1, "Q2": 2, "H1": 3, "Q3": 4, "Q4": 5, "FY": 6}


class Task3Runtime:
    def __init__(
        self,
        config: Task3LangGraphConfig,
        *,
        index_progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.index_progress_callback = index_progress_callback
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.result_dir.mkdir(parents=True, exist_ok=True)
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.config.debug_dir.mkdir(parents=True, exist_ok=True)
        self.config.retrieval_dir.mkdir(parents=True, exist_ok=True)
        self.config.chart_spec_dir.mkdir(parents=True, exist_ok=True)
        self.config.vector_store_dir.mkdir(parents=True, exist_ok=True)
        self.config.chunk_dir.mkdir(parents=True, exist_ok=True)
        self.sql_cache_dir = self.config.artifacts_dir / "sql_cache"
        self.retrieval_cache_dir = self.config.artifacts_dir / "retrieval_cache"
        self.sql_cache_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_cache_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(config.database_url)
        self.view_df = self._build_view()
        self._write_query_cache()

        company_reference = pd.read_excel(config.company_info_path, sheet_name=0)
        stock_report_info = pd.read_excel(config.stock_report_info_path)
        industry_report_info = pd.read_excel(config.industry_report_info_path)
        self.stock_report_count = len(stock_report_info)
        self.industry_report_count = len(industry_report_info)
        self.report_field_descriptions = load_field_descriptions(config.report_field_desc_path)
        self.report_metadata_lookup = build_report_metadata_lookup(
            stock_report_info,
            industry_report_info,
            field_descriptions=self.report_field_descriptions,
        )
        extra_names = stock_report_info.get("stockName", pd.Series(dtype=str)).dropna().astype(str).tolist()
        self.intent_parser = Task3IntentParser(company_reference, extra_company_names=extra_names)
        self.questions = {question.question_id: question for question in load_questions(config.question_file)}
        self.prompt_manager = PromptManager(config.base_dir / "src/task3_langgraph/prompts")
        self.metadata_retriever = MetadataRetriever(
            stock_reports=stock_report_info,
            industry_reports=industry_report_info,
            stock_report_dir=config.stock_report_dir,
            industry_report_dir=config.industry_report_dir,
        )
        self.vector_store = VectorStoreManager(config.vector_store_dir)
        self.embedding_client = None
        if config.embedding_base_url and config.embedding_api_key and config.embedding_model:
            self.embedding_client = OpenAICompatibleEmbeddingClient(
                config.embedding_base_url,
                config.embedding_api_key,
                config.embedding_model,
            )
        self.reranker_client = None
        if config.rerank_base_url and config.rerank_api_key and config.rerank_model:
            self.reranker_client = OpenAICompatibleRerankerClient(
                config.rerank_base_url,
                config.rerank_api_key,
                config.rerank_model,
            )
        self.chunk_manifest = self._load_or_build_chunk_manifest(
            stock_report_info=stock_report_info,
            industry_report_info=industry_report_info,
        )
        self.chunks_by_metadata_ref = self._build_chunk_lookup(self.chunk_manifest)
        self._write_chunk_manifest()
        self._write_metadata_lookup()
        self._prepare_vector_index()
        self.vector_retriever = VectorRetriever(self.vector_store, self.embedding_client)
        self.retriever = HybridRetriever(self.metadata_retriever, self.vector_retriever)

        if not (config.llm_base_url and config.llm_api_key and config.llm_model):
            raise ValueError(
                "task3_langgraph is llm-only. Please provide TASK3_LLM_BASE_URL, "
                "TASK3_LLM_API_KEY, TASK3_LLM_MODEL."
            )
        self.llm_client = OpenAICompatibleClient(config.llm_base_url, config.llm_api_key, config.llm_model)

    def get_question(self, question_id: str) -> QuestionRecord:
        if question_id not in self.questions:
            raise KeyError(f"Question id not found: {question_id}")
        return self.questions[question_id]

    def build_query_plan(
        self,
        question: str,
        parsed_slots: dict[str, object],
        context_companies: list[str] | None = None,
        context_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        default_plan = {
            "intent_type": parsed_slots.get("intent_type"),
            "companies": list(parsed_slots.get("companies", [])),
            "periods": parsed_slots.get("periods", []),
            "metrics": parsed_slots.get("metrics", []),
            "needs_sql": bool(parsed_slots.get("needs_sql")),
            "top_n": parsed_slots.get("top_n"),
            "threshold": parsed_slots.get("threshold"),
            "question": question,
        }
        try:
            system_prompt = self.prompt_manager.load("query_plan_system")
            user_prompt = (
                f"Question: {question}\n"
                f"Parsed slots: {parsed_slots}\n"
                f"Previous cohort companies: {context_companies or []}\n"
                f"Previous turn rows: {json.dumps((context_rows or [])[:10], ensure_ascii=False)}\n"
                "Please refine the task3 SQL query plan."
            )
            payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
            default_plan.update({k: v for k, v in payload.items() if v is not None})
        except Exception:
            pass
        parsed_threshold = parsed_slots.get("threshold")
        if parsed_threshold not in (None, ""):
            try:
                parsed_threshold_value = float(parsed_threshold)
                plan_threshold = default_plan.get("threshold")
                if plan_threshold in (None, ""):
                    default_plan["threshold"] = parsed_threshold_value
                else:
                    plan_threshold_value = float(plan_threshold)
                    if plan_threshold_value > parsed_threshold_value * 100 or plan_threshold_value < parsed_threshold_value / 100:
                        default_plan["threshold"] = parsed_threshold_value
            except Exception:
                default_plan["threshold"] = parsed_threshold
        if parsed_slots.get("metrics"):
            default_plan["metrics"] = list(parsed_slots.get("metrics", []))
        if parsed_slots.get("periods"):
            default_plan["periods"] = list(parsed_slots.get("periods", []))
        if parsed_slots.get("companies"):
            default_plan["companies"] = list(parsed_slots.get("companies", []))
        return default_plan

    def build_plans(
        self,
        question: str,
        parsed_slots: dict[str, object],
        *,
        context_companies: list[str] | None = None,
        context_rows: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        intent_type = str(parsed_slots.get("intent_type", "") or "")
        retrieval_must_run = bool(parsed_slots.get("needs_retrieval", True)) or intent_type in {
            "causal_analysis",
            "industry_open_analysis",
            "hybrid_sql_rag",
            "rag_only",
            "open_analysis",
        }
        default_needs_retrieval = bool(parsed_slots.get("needs_retrieval", True))
        default_source_scope = "hybrid"
        default_top_k = 5
        if intent_type in {"sql_only", "sql_chart"}:
            default_needs_retrieval = False
            default_top_k = 0
        elif intent_type == "causal_analysis":
            default_needs_retrieval = True
            default_top_k = 8
            default_source_scope = "stock" if parsed_slots.get("companies") else "hybrid"
        elif intent_type == "industry_open_analysis":
            default_needs_retrieval = True
            default_top_k = 8
            default_source_scope = "industry"
        default_query_plan = {
            "intent_type": intent_type,
            "companies": list(parsed_slots.get("companies", [])),
            "periods": parsed_slots.get("periods", []),
            "metrics": parsed_slots.get("metrics", []),
            "needs_sql": bool(parsed_slots.get("needs_sql")),
            "top_n": parsed_slots.get("top_n"),
            "threshold": parsed_slots.get("threshold"),
            "question": question,
        }
        default_retrieval_plan = {
            "question": question,
            "companies": list(parsed_slots.get("companies", [])),
            "focus_topics": list(parsed_slots.get("focus_topics", [])),
            "needs_retrieval": default_needs_retrieval,
            "top_k": default_top_k,
            "source_scope": default_source_scope,
            "retrieval_mode": "hybrid" if self.embedding_client else "metadata",
        }
        try:
            system_prompt = self.prompt_manager.load("planning_system")
            user_prompt = (
                f"Question: {question}\n"
                f"Parsed slots: {json.dumps(parsed_slots, ensure_ascii=False)}\n"
                f"Previous cohort companies: {context_companies or []}\n"
                f"Previous turn rows: {json.dumps((context_rows or [])[:10], ensure_ascii=False)}\n"
                "请一次性输出 query_plan 和 retrieval_plan。"
            )
            payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
            query_plan = dict(default_query_plan)
            retrieval_plan = dict(default_retrieval_plan)
            query_plan.update({k: v for k, v in dict(payload.get("query_plan", {}) or {}).items() if v is not None})
            retrieval_plan.update({k: v for k, v in dict(payload.get("retrieval_plan", {}) or {}).items() if v is not None})
            if parsed_slots.get("metrics"):
                query_plan["metrics"] = list(parsed_slots.get("metrics", []) or [])
            if parsed_slots.get("periods"):
                query_plan["periods"] = list(parsed_slots.get("periods", []) or [])
            if parsed_slots.get("companies"):
                query_plan["companies"] = list(parsed_slots.get("companies", []) or [])
            if retrieval_must_run:
                retrieval_plan["needs_retrieval"] = True
                retrieval_plan["top_k"] = max(int(retrieval_plan.get("top_k", 5) or 5), default_top_k or 5)
                if not retrieval_plan.get("companies") and parsed_slots.get("companies"):
                    retrieval_plan["companies"] = list(parsed_slots.get("companies", []) or [])
                if not retrieval_plan.get("focus_topics") and parsed_slots.get("focus_topics"):
                    retrieval_plan["focus_topics"] = list(parsed_slots.get("focus_topics", []) or [])
            retrieval_plan = self._normalize_retrieval_plan(question, retrieval_plan, parsed_slots)
            return query_plan, retrieval_plan
        except Exception:
            return default_query_plan, self._normalize_retrieval_plan(question, default_retrieval_plan, parsed_slots)

    def build_retrieval_plan(
        self,
        question: str,
        parsed_slots: dict[str, object],
    ) -> dict[str, object]:
        default_plan = {
            "question": question,
            "companies": list(parsed_slots.get("companies", [])),
            "focus_topics": list(parsed_slots.get("focus_topics", [])),
            "needs_retrieval": bool(parsed_slots.get("needs_retrieval", True)),
            "top_k": 5,
            "source_scope": "hybrid",
            "retrieval_mode": "hybrid" if self.embedding_client else "metadata",
        }
        try:
            system_prompt = self.prompt_manager.load("retrieval_plan_system")
            user_prompt = f"Question: {question}\nParsed slots: {parsed_slots}\nPlease refine the retrieval plan."
            payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
            default_plan.update({k: v for k, v in payload.items() if v is not None})
        except Exception:
            pass
        return self._normalize_retrieval_plan(question, default_plan, parsed_slots)

    def generate_sql(
        self,
        question: str,
        query_plan: dict[str, object] | None = None,
        context_rows: list[dict[str, Any]] | None = None,
        previous_sql: str | None = None,
        previous_error: str | None = None,
    ) -> tuple[str, str]:
        if not query_plan or not query_plan.get("needs_sql"):
            return "", ""
        system_prompt = self.prompt_manager.load("sql_generation_system")
        user_prompt = (
            f"{self._schema_text()}\n\n"
            f"Question: {question}\n"
            f"Query plan: {json.dumps(query_plan or {}, ensure_ascii=False)}\n"
        )
        if not (query_plan or {}).get("companies"):
            user_prompt += (
                "Important: if the query plan does not explicitly provide companies, "
                "do not invent or manually enumerate a stock_abbr IN (...) list.\n"
            )
        if any(str(period).endswith(("Q2", "Q4")) for period in (query_plan or {}).get("periods", []) or []):
            user_prompt += (
                "Important: financials_view already contains derived single-quarter rows such as Q2/Q4 when they "
                "can be reconstructed from cumulative disclosures, so you may query 2025Q2/2025Q4 directly.\n"
            )
        user_prompt += (
            "SQLite compatibility: do not use PERCENTILE_CONT / WITHIN GROUP. "
            "If median is needed, emulate it with ROW_NUMBER() and COUNT() window functions.\n"
        )
        if context_rows:
            user_prompt += f"Previous turn result rows: {json.dumps(context_rows[:12], ensure_ascii=False)}\n"
        if previous_sql or previous_error:
            user_prompt += f"Previous SQL: {previous_sql or ''}\nPrevious error: {previous_error or ''}\nPlease repair it.\n"
        payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
        sql = str(payload.get("sql", "")).strip()
        if sql:
            sql = self._normalize_threshold_literals(sql, query_plan or {})
            self.validate_sql(sql)
        return sql, str(payload.get("reason", "")).strip()

    def validate_sql(self, sql: str) -> None:
        lowered = " ".join(sql.strip().lower().split())
        if not lowered.startswith(SAFE_SQL_PREFIXES):
            raise ValueError("Only SELECT/CTE queries are allowed.")
        if "financials_view" not in lowered:
            raise ValueError("SQL must query financials_view.")
        for token in FORBIDDEN_SQL_TOKENS:
            if token in lowered:
                raise ValueError(f"Forbidden SQL token detected: {token}")

    def run_sql(self, sql: str) -> pd.DataFrame:
        if not sql.strip():
            return pd.DataFrame()
        cache_path = self._sql_cache_path(sql)
        cached = self._load_json_cache(cache_path)
        if isinstance(cached, list):
            return pd.DataFrame(cached)
        conn = sqlite3.connect(self.config.query_cache_db)
        try:
            df = pd.read_sql_query(sql, conn)
        finally:
            conn.close()
        self._write_json_cache(cache_path, df.to_dict(orient="records"))
        return df

    def retrieve_evidence(self, retrieval_plan: dict[str, object]) -> list[dict[str, Any]]:
        normalized_plan = self._normalize_retrieval_plan(
            str(retrieval_plan.get("question", "") or ""),
            retrieval_plan,
            {
                "companies": list(retrieval_plan.get("companies", []) or []),
                "focus_topics": list(retrieval_plan.get("focus_topics", []) or []),
                "needs_retrieval": bool(retrieval_plan.get("needs_retrieval", True)),
            },
        )
        if not normalized_plan.get("needs_retrieval", True):
            return []
        cache_path = self._retrieval_cache_path(normalized_plan)
        cached = self._load_json_cache(cache_path)
        if isinstance(cached, list):
            return cached
        hits = self.retriever.retrieve(normalized_plan)
        if not hits:
            fallback_plan = self._fallback_retrieval_plan(normalized_plan)
            if fallback_plan is not None:
                hits = self.retriever.retrieve(fallback_plan)
        self._write_json_cache(cache_path, hits)
        return hits

    def rerank_evidence(
        self,
        question: str,
        retrieval_plan: dict[str, object],
        evidences: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not evidences:
            return [], {"strategy": "empty", "kept_count": 0}
        default_ranked = sorted(
            evidences,
            key=lambda item: float(item.get("score", 0.0)),
            reverse=True,
        )
        default_ranked = self._deduplicate_evidences(default_ranked)[: int(retrieval_plan.get("top_k", 5) or 5)]
        if self.reranker_client:
            try:
                documents = [self._evidence_to_rerank_text(item) for item in evidences[:20]]
                rerank_results = self.reranker_client.rerank(
                    question,
                    documents,
                    top_n=min(int(retrieval_plan.get("top_k", 5) or 5), len(documents)),
                )
                reranked = []
                for item in rerank_results:
                    idx = item.get("index")
                    if isinstance(idx, str) and idx.isdigit():
                        idx = int(idx)
                    if isinstance(idx, (int, float)):
                        pos = int(idx)
                        if 0 <= pos < len(evidences[:20]):
                            reranked.append(dict(evidences[pos]))
                reranked = self._deduplicate_evidences(reranked)
                if reranked:
                    return reranked, {
                        "strategy": "reranker_model",
                        "kept_count": len(reranked),
                        "reason": self.config.rerank_model or "",
                    }
            except Exception:
                pass
        try:
            system_prompt = self.prompt_manager.load("evidence_rerank_system")
            user_prompt = (
                f"Question: {question}\n"
                f"Retrieval plan: {json.dumps(retrieval_plan, ensure_ascii=False)}\n"
                f"Evidences: {json.dumps(evidences[:10], ensure_ascii=False)}"
            )
            payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
            keep_indices = [int(idx) for idx in payload.get("keep_indices", []) if isinstance(idx, (int, float, str))]
            reranked: list[dict[str, Any]] = []
            for idx in keep_indices:
                if 0 <= idx < len(evidences):
                    reranked.append(dict(evidences[idx]))
            reranked = self._deduplicate_evidences(reranked)
            if not reranked:
                reranked = default_ranked
            return reranked, {
                "strategy": "llm",
                "kept_count": len(reranked),
                "reason": str(payload.get("reason", "")).strip(),
            }
        except Exception as exc:
            return default_ranked, {
                "strategy": "score_fallback",
                "kept_count": len(default_ranked),
                "reason": str(exc),
            }

    def should_rerank(
        self,
        question: str,
        retrieval_plan: dict[str, object],
        evidences: list[dict[str, Any]],
    ) -> bool:
        evidence_count = len(evidences)
        if evidence_count <= 5:
            return False
        if self._is_simple_fact_question(question):
            return False
        if self._question_requires_chart(question):
            return False
        retrieval_mode = str(retrieval_plan.get("retrieval_mode", "") or "")
        source_scope = str(retrieval_plan.get("source_scope", "") or "")
        complex_reasoning = any(token in question for token in ["为什么", "原因", "共同点", "关系", "影响", "分析", "依据", "判断依据", "驱动"])
        if retrieval_mode == "metadata" and evidence_count <= 8:
            return False
        if not complex_reasoning and evidence_count <= 8:
            return False
        source_types = {str(item.get("source_type", "") or "") for item in evidences}
        companies = {
            str(item.get("company_or_industry", "") or "").strip()
            for item in evidences
            if str(item.get("source_type", "") or "") == "stock" and str(item.get("company_or_industry", "") or "").strip()
        }
        if source_types == {"stock"} and len(companies) <= 1 and evidence_count <= 12:
            return False
        if source_scope == "stock" and len(companies) <= 1 and evidence_count <= 10:
            return False
        if len(source_types) <= 1 and evidence_count <= 8:
            return False
        if self._top_scores_are_clearly_separated(evidences):
            return False
        return True

    def retrieval_smoke_test(
        self,
        question: str,
        *,
        companies: list[str] | None = None,
        focus_topics: list[str] | None = None,
        top_k: int = 5,
        source_scope: str = "hybrid",
        retrieval_mode: str | None = None,
    ) -> dict[str, Any]:
        intent = self.intent_parser.parse_text(question)
        parsed_slots = {
            "companies": companies if companies is not None else list(intent.companies),
            "focus_topics": focus_topics if focus_topics is not None else list(intent.focus_topics),
            "needs_retrieval": intent.needs_retrieval,
        }
        plan = self.build_retrieval_plan(question, parsed_slots)
        plan["top_k"] = top_k
        plan["source_scope"] = source_scope if source_scope else str(plan.get("source_scope", "hybrid"))
        plan["retrieval_mode"] = retrieval_mode or str(plan.get("retrieval_mode", "hybrid" if self.embedding_client else "metadata"))
        hits = self.retrieve_evidence(plan)
        return {
            "retrieval_plan": plan,
            "vector_store_meta": self.vector_store.load_index_meta(),
            "chunk_count": len(self.chunk_manifest),
            "hits": hits,
        }

    def fuse_context(
        self,
        question: str,
        sql_rows: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence_titles = [str(item.get("title", "") or "") for item in evidences[:5]]
        source_breakdown: dict[str, int] = {}
        for item in evidences:
            source_type = str(item.get("source_type", "") or "unknown")
            source_breakdown[source_type] = source_breakdown.get(source_type, 0) + 1
        return {
            "question": question,
            "sql_row_count": len(sql_rows),
            "evidence_count": len(evidences),
            "sql_preview": sql_rows[:5],
            "evidence_preview": evidences[:5],
            "evidence_titles": evidence_titles,
            "source_breakdown": source_breakdown,
        }

    def self_check(
        self,
        question: str,
        answer: str,
        sql_rows: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            system_prompt = self.prompt_manager.load("self_check_system")
            user_prompt = (
                f"Question: {question}\n"
                f"Answer: {answer}\n"
                f"SQL rows: {json.dumps(sql_rows[:10], ensure_ascii=False)}\n"
                f"Evidences: {json.dumps(evidences[:5], ensure_ascii=False)}"
            )
            payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
            return payload
        except Exception:
            return {"pass": True, "notes": ["self_check_skipped"]}

    def should_run_self_check(
        self,
        question: str,
        query_plan: dict[str, Any] | None,
        query_result: pd.DataFrame,
        evidences: list[dict[str, Any]],
    ) -> bool:
        analysis_tokens = ["共同点", "关系", "影响", "分析", "可视化", "差异", "对比"]
        reason_tokens = ["为什么", "原因"]
        evidence_source_types = {str(item.get("source_type", "") or "") for item in evidences}
        evidence_companies = {
            str(item.get("company_or_industry", "") or "").strip()
            for item in evidences
            if str(item.get("source_type", "") or "") == "stock" and str(item.get("company_or_industry", "") or "").strip()
        }
        if self._question_requires_chart(question) and bool((query_plan or {}).get("needs_sql")):
            return False
        if self._is_simple_fact_question(question) and len(query_result) <= 3 and len(evidences) <= 3:
            return False
        if not evidences and self._can_short_circuit_without_evidence(question, query_plan, query_result):
            return False
        if (
            any(token in question for token in reason_tokens)
            and len(query_result) <= 3
            and 0 < len(evidences) <= 8
            and evidence_source_types == {"stock"}
            and len(evidence_companies) <= 1
        ):
            return False
        if not evidences and len(query_result) <= 3:
            if any(token in question for token in reason_tokens) and not any(token in question for token in analysis_tokens):
                return False
        if len(query_result) > 1 or len(evidences) > 3:
            return True
        if any(token in question for token in reason_tokens + analysis_tokens):
            return True
        if bool((query_plan or {}).get("needs_sql")) and bool(evidences):
            return True
        return False

    def should_rewrite_after_self_check(
        self,
        question: str,
        query_plan: dict[str, Any] | None,
        query_result: pd.DataFrame,
        evidences: list[dict[str, Any]],
        self_check: dict[str, Any],
    ) -> bool:
        if bool(self_check.get("pass", True)):
            return False
        if self._question_requires_chart(question) and bool((query_plan or {}).get("needs_sql")):
            return False
        if not evidences and self._can_short_circuit_without_evidence(question, query_plan, query_result):
            return False
        if not evidences and len(query_result) <= 3 and not any(
            token in question for token in ["共同点", "关系", "影响", "分析", "对比", "差异"]
        ):
            return False
        notes = " ".join(str(item) for item in self_check.get("notes", []) if item)
        support_only_patterns = [
            r"仅引用了标题",
            r"未提供.*正文",
            r"未提供.*具体解释",
            r"缺乏实质性内容",
            r"证据支撑.*不足",
            r"研报证据支撑.*缺乏",
            r"由于证据缺失",
            r"回答本身是诚实的",
            r"未检索到直接.*原因",
        ]
        severe_patterns = [
            r"数字.*不一致",
            r"引用.*不准确",
            r"错误地将聚合",
            r"聚合统计结果.*具体公司",
            r"混淆",
            r"遗漏.*关键",
            r"与SQL rows.*矛盾",
            r"错误对应",
        ]
        if any(re.search(pattern, notes) for pattern in support_only_patterns) and not any(
            re.search(pattern, notes) for pattern in severe_patterns
        ):
            return False
        return any(re.search(pattern, notes) for pattern in severe_patterns)

    def generate_answer(
        self,
        question: str,
        sql: str,
        query_plan: dict[str, Any] | None,
        query_result: pd.DataFrame,
        evidences: list[dict[str, Any]],
    ) -> str:
        deterministic = self._deterministic_sql_answer(question, query_plan or {}, query_result)
        if deterministic:
            return deterministic
        system_prompt = self.prompt_manager.load("answer_generation_system")
        answer_constraints = self._derive_answer_constraints(question, query_plan or {}, query_result)
        user_prompt = (
            f"Question: {question}\n"
            f"Query plan: {json.dumps(query_plan or {}, ensure_ascii=False)}\n"
            f"SQL: {sql}\n"
            f"Rows: {query_result.head(20).to_json(force_ascii=False, orient='records')}\n"
            f"Evidences: {json.dumps(evidences[:5], ensure_ascii=False)}\n"
            f"Answer constraints: {json.dumps(answer_constraints, ensure_ascii=False)}\n"
            "请直接给出中文回答。"
        )
        return self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()

    def _deterministic_sql_answer(
        self,
        question: str,
        query_plan: dict[str, Any],
        query_result: pd.DataFrame,
    ) -> str:
        intent_type = str(query_plan.get("intent_type", "") or "")
        threshold = query_plan.get("threshold")
        top_n = query_plan.get("top_n")
        metrics = list(query_plan.get("metrics", []) or [])
        if intent_type not in {"sql_only", "sql_chart"}:
            return ""
        if threshold in (None, "") and top_n in (None, ""):
            return ""
        if not metrics:
            return ""
        metric_label = str(metrics[0])
        if query_result.empty:
            threshold_text = ""
            if threshold not in (None, ""):
                threshold_text = f"超过{float(threshold) / 10000:.0f}亿元" if float(threshold) >= 10000 else f"超过{threshold}"
            return (
                f"根据查询结果，当前数据库中未找到满足条件的公司。"
                f"{' 条件为：' + threshold_text if threshold_text else ''}"
            ).strip()
        if not {"stock_abbr", "stock_code"}.issubset(query_result.columns):
            return ""
        value_field = None
        for candidate in ["total_operating_revenue", "net_profit", "total_profit", "roe"]:
            if candidate in query_result.columns:
                value_field = candidate
                break
        if value_field is None:
            numeric_cols = [col for col in query_result.columns if pd.to_numeric(query_result[col], errors="coerce").notna().sum() > 0]
            value_field = numeric_cols[0] if numeric_cols else None
        if value_field is None:
            return ""
        rows = query_result.head(int(top_n or len(query_result))).to_dict(orient="records")
        lines = []
        for idx, row in enumerate(rows, start=1):
            stock_abbr = str(row.get("stock_abbr", "") or "").strip()
            stock_code = str(row.get("stock_code", "") or "").strip()
            raw_value = row.get(value_field)
            if raw_value is None or raw_value == "":
                continue
            try:
                value = float(raw_value)
            except Exception:
                continue
            if metric_label in {"营业总收入", "主营业务收入", "营业收入"}:
                value_text = f"{value / 10000:.2f}亿元"
            elif metric_label in {"净利润", "利润总额"}:
                value_text = f"{value / 10000:.2f}亿元" if abs(value) >= 10000 else f"{value:.2f}万元"
            elif metric_label == "ROE":
                value_text = f"{value:.2f}%"
            else:
                value_text = f"{value:.2f}"
            lines.append(f"{idx}. **{stock_abbr} ({stock_code})**：{metric_label}为{value_text}。")
        if not lines:
            return ""
        prefix = "根据SQL查询结果，满足条件的公司如下："
        if "共同点" in question:
            prefix = "根据SQL查询结果，这些公司的共同点如下："
        summary = ""
        if "共同点" in question and metric_label in {"营业总收入", "主营业务收入", "营业收入"} and threshold not in (None, ""):
            threshold_text = f"{float(threshold) / 10000:.0f}亿元" if float(threshold) >= 10000 else str(threshold)
            summary = f"\n\n**直接结论**：这些公司在当前报告期的{metric_label}均超过{threshold_text}，属于该指标规模最高的一组公司。"
        return prefix + "\n" + "\n".join(lines) + summary

    def rewrite_answer(
        self,
        question: str,
        sql: str,
        query_plan: dict[str, Any] | None,
        query_result: pd.DataFrame,
        evidences: list[dict[str, Any]],
        previous_answer: str,
        self_check: dict[str, Any],
    ) -> str:
        system_prompt = self.prompt_manager.load("answer_generation_system")
        answer_constraints = self._derive_answer_constraints(question, query_plan or {}, query_result)
        user_prompt = (
            f"Question: {question}\n"
            f"Query plan: {json.dumps(query_plan or {}, ensure_ascii=False)}\n"
            f"SQL: {sql}\n"
            f"Rows: {query_result.head(20).to_json(force_ascii=False, orient='records')}\n"
            f"Evidences: {json.dumps(evidences[:5], ensure_ascii=False)}\n"
            f"Answer constraints: {json.dumps(answer_constraints, ensure_ascii=False)}\n"
            f"Previous answer: {previous_answer}\n"
            f"Self-check findings: {json.dumps(self_check, ensure_ascii=False)}\n"
            "请根据自检意见重写答案，修复其中指出的问题。请直接给出中文回答。"
        )
        return self.llm_client.chat(system_prompt, user_prompt, temperature=0.1).strip()

    def enrich_reference(self, evidence: dict[str, Any], *, question: str = "") -> dict[str, Any]:
        metadata_ref = str(evidence.get("metadata_ref", "") or "")
        metadata = self.report_metadata_lookup.get(metadata_ref, {}) if metadata_ref else {}
        reference_chunk = self._select_reference_chunk(evidence, question=question)
        visual_chunk = self._select_visual_reference_chunk(
            evidence,
            reference_chunk=reference_chunk,
            question=question,
        )
        chunk_text = (
            str(evidence.get("text", "") or "")
            or str(reference_chunk.get("text", "") or "")
            or str(evidence.get("snippet", "") or "")
        ).strip()
        figure_refs = list(evidence.get("figure_table_refs", []) or [])
        if not figure_refs:
            figure_refs = list(reference_chunk.get("figure_table_refs", []) or [])
        if not figure_refs and visual_chunk:
            figure_refs = list(visual_chunk.get("figure_table_refs", []) or [])
        visual_caption = self._format_visual_caption(
            evidence.get("visual_caption")
            or reference_chunk.get("visual_caption")
            or (visual_chunk or {}).get("visual_caption")
        )
        paper_image = ""
        if figure_refs:
            formatted_refs = []
            for item in figure_refs[:3]:
                formatted = self._format_visual_caption(item)
                if formatted:
                    formatted_refs.append(formatted)
            if formatted_refs:
                paper_image = "；".join(formatted_refs)
        if visual_caption:
            if not paper_image:
                paper_image = visual_caption
            elif visual_caption not in paper_image:
                paper_image = f"{paper_image}；{visual_caption}"
        page_start = evidence.get("page_start") or evidence.get("page") or reference_chunk.get("page_start") or reference_chunk.get("page")
        page_end = evidence.get("page_end") or reference_chunk.get("page_end") or page_start
        page_ref = ""
        if page_start and page_end:
            page_ref = f"第{page_start}页" if page_start == page_end else f"第{page_start}-{page_end}页"
        reference_path = evidence.get("relative_path", "") or metadata.get("path", "")
        reference: dict[str, Any] = {
            "paper_path": self._to_reference_relative_path(reference_path),
            "text": chunk_text[:600],
        }
        if paper_image:
            reference["paper_image"] = paper_image
        return reference

    def build_references(
        self,
        evidences: list[dict[str, Any]],
        *,
        question: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        evidence_list = list(evidences or [])
        initial = evidence_list[:limit]
        references = [self.enrich_reference(item, question=question) for item in initial]
        if any(ref.get("paper_image") for ref in references):
            return references
        fallback_reference: dict[str, Any] | None = None
        for item in evidence_list[limit: min(len(evidence_list), 20)]:
            candidate = self.enrich_reference(item, question=question)
            if candidate.get("paper_image"):
                fallback_reference = candidate
                break
        if not fallback_reference:
            return references
        fallback_key = (
            fallback_reference.get("paper_path", ""),
            fallback_reference.get("text", ""),
            fallback_reference.get("paper_image", ""),
        )
        existing_keys = {
            (
                ref.get("paper_path", ""),
                ref.get("text", ""),
                ref.get("paper_image", ""),
            )
            for ref in references
        }
        if fallback_key in existing_keys:
            return references
        if len(references) < limit:
            references.append(fallback_reference)
            return references
        references[-1] = fallback_reference
        return references

    def canonicalize_company_name(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = self.intent_parser._normalize_company_text(text)
        if normalized in self.intent_parser._normalized_company_map:
            return self.intent_parser._normalized_company_map[normalized]
        for name in self.intent_parser.company_names:
            if name and (name in text or normalized in self.intent_parser._normalize_company_text(name)):
                return name
        return ""

    def derive_companies_from_evidences(self, evidences: list[dict[str, Any]], *, question: str = "") -> list[str]:
        companies: list[str] = []
        for item in evidences or []:
            if str(item.get("source_type", "") or "") != "stock":
                continue
            metadata_ref = str(item.get("metadata_ref", "") or "")
            metadata = self.report_metadata_lookup.get(metadata_ref, {}) if metadata_ref else {}
            if not self._evidence_matches_question_event(item, metadata, question):
                continue
            candidates = [
                str(item.get("company_or_industry", "") or ""),
                str(item.get("company", "") or ""),
                str(metadata.get("company", "") or ""),
            ]
            for candidate in candidates:
                canonical = self.canonicalize_company_name(candidate)
                if canonical and canonical not in companies:
                    companies.append(canonical)
        return companies

    def _evidence_matches_question_event(
        self,
        evidence: dict[str, Any],
        metadata: dict[str, Any],
        question: str,
    ) -> bool:
        text = "\n".join(
            part
            for part in [
                str(evidence.get("title", "") or ""),
                str(evidence.get("snippet", "") or ""),
                str(evidence.get("text", "") or ""),
                str(metadata.get("title", "") or ""),
            ]
            if part
        )
        if "资产重组" in question:
            return any(
                token in text
                for token in ["资产重组", "重大资产重组", "控股股东变更", "控制权变更", "股权转让"]
            )
        if "商誉减值风险" in question:
            return "商誉" in text and "减值" in text
        if "应收账款回收风险" in question:
            return "应收账款" in text and any(token in text for token in ["回收风险", "回款风险", "回收不及预期"])
        if "FDA" in question or "认证" in question:
            return "FDA" in text and "认证" in text
        if "集采" in question:
            return any(token in text for token in ["集采", "中标"])
        if "业绩预告" in question:
            return "业绩预告" in text
        return True

    def generate_clarification(self, question: str, missing_slots: list[str]) -> str:
        if not missing_slots:
            return ""
        try:
            system_prompt = self.prompt_manager.load("clarification_system")
            user_prompt = f"Question: {question}\nMissing slots: {missing_slots}"
            response = self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()
            if response:
                return response
        except Exception:
            pass
        return self._deterministic_clarification(missing_slots)

    def _deterministic_clarification(self, missing_slots: list[str]) -> str:
        missing = set(str(item) for item in missing_slots if str(item).strip())
        if missing == {"metric"}:
            return "请补充想看的具体财务指标，例如营业总收入、净利润或资产负债率。"
        if missing == {"period"}:
            return "请补充具体报告期，例如2025年第三季度或2025年全年。"
        if missing == {"company"}:
            return "请补充公司名称或股票代码。"
        if missing == {"period", "metric"}:
            return "请补充具体报告期和财务指标，例如2025年第三季度的营业总收入。"
        if missing == {"company", "metric"}:
            return "请补充公司名称和财务指标，例如云南白药的净利润。"
        if missing == {"company", "period"}:
            return "请补充公司名称和报告期，例如云南白药2025年第三季度。"
        missing_text = "、".join(str(item) for item in missing_slots if item) or "关键信息"
        return f"请补充继续分析所需的关键信息：{missing_text}。"

    def _build_view(self) -> pd.DataFrame:
        key_cols = ["stock_code", "stock_abbr", "report_period", "report_year"]
        kpi = pd.read_sql_table("core_performance_indicators_sheet", self.engine)
        bal = pd.read_sql_table("balance_sheet", self.engine)
        cash = pd.read_sql_table("cash_flow_sheet", self.engine)
        inc = pd.read_sql_table("income_sheet", self.engine)

        def ensure_columns(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
            subset = frame.copy()
            for col in cols:
                if col not in subset.columns:
                    subset[col] = pd.NA
            return subset

        view = pd.concat([frame[key_cols] for frame in [kpi, bal, cash, inc]], ignore_index=True).drop_duplicates()

        kpi_subset = kpi[
            key_cols
            + [
                "total_operating_revenue",
                "operating_revenue_yoy_growth",
                "operating_revenue_qoq_growth",
                "net_profit_10k_yuan",
                "net_profit_yoy_growth",
                "net_profit_qoq_growth",
                "gross_profit_margin",
                "net_profit_margin",
                "roe",
                "net_profit_excl_non_recurring",
            ]
        ].rename(
            columns={
                "total_operating_revenue": "kpi_total_operating_revenue",
                "operating_revenue_yoy_growth": "kpi_operating_revenue_yoy_growth",
                "operating_revenue_qoq_growth": "kpi_operating_revenue_qoq_growth",
                "net_profit_10k_yuan": "kpi_net_profit",
                "net_profit_yoy_growth": "kpi_net_profit_yoy_growth",
                "net_profit_qoq_growth": "kpi_net_profit_qoq_growth",
            }
        )
        inc_cols = [
            "net_profit",
            "net_profit_yoy_growth",
            "total_operating_revenue",
            "operating_revenue_yoy_growth",
            "total_profit",
            "operating_expense_rnd_expenses",
            "operating_expense_selling_expenses",
            "operating_expense_cost_of_sales",
            "operating_expense_administrative_expenses",
            "operating_expense_financial_expenses",
            "operating_expense_taxes_and_surcharges",
            "total_operating_expenses",
        ]
        inc = ensure_columns(inc, inc_cols)
        inc_subset = inc[
            key_cols
            + inc_cols
        ].rename(
            columns={
                "net_profit": "income_net_profit",
                "net_profit_yoy_growth": "income_net_profit_yoy_growth",
                "total_operating_revenue": "income_total_operating_revenue",
                "operating_revenue_yoy_growth": "income_operating_revenue_yoy_growth",
            }
        )
        view = view.merge(kpi_subset, on=key_cols, how="left")
        view = view.merge(inc_subset, on=key_cols, how="left")
        view = view.merge(
            bal[
                key_cols
                + [
                    "asset_liability_ratio",
                    "asset_cash_and_cash_equivalents",
                    "liability_short_term_loans",
                    "equity_unappropriated_profit",
                    "equity_total_equity",
                    "asset_total_assets",
                    "asset_accounts_receivable",
                    "asset_inventory",
                ]
            ],
            on=key_cols,
            how="left",
        )
        view = view.merge(cash[key_cols + ["operating_cf_net_amount", "investing_cf_net_amount", "financing_cf_net_amount", "net_cash_flow"]], on=key_cols, how="left")

        view["total_operating_revenue"] = view["income_total_operating_revenue"].combine_first(view["kpi_total_operating_revenue"])
        view["operating_revenue_yoy_growth"] = view["income_operating_revenue_yoy_growth"].combine_first(view["kpi_operating_revenue_yoy_growth"])
        view["operating_revenue_qoq_growth"] = view["kpi_operating_revenue_qoq_growth"]
        view["net_profit"] = view["income_net_profit"].combine_first(view["kpi_net_profit"])
        view["net_profit_yoy_growth"] = view["income_net_profit_yoy_growth"].combine_first(view["kpi_net_profit_yoy_growth"])
        view["net_profit_qoq_growth"] = view["kpi_net_profit_qoq_growth"]
        view["total_assets"] = view["asset_total_assets"]
        view["total_equity"] = view["equity_total_equity"]
        view["accounts_receivable"] = view["asset_accounts_receivable"]
        view["operating_cost"] = view["operating_expense_cost_of_sales"]
        view["selling_expenses"] = view["operating_expense_selling_expenses"]
        view["administrative_expenses"] = view["operating_expense_administrative_expenses"]
        view["financial_expenses"] = view["operating_expense_financial_expenses"]
        view["taxes_and_surcharges"] = view["operating_expense_taxes_and_surcharges"]
        view["total_operating_expenses"] = view["total_operating_expenses"]
        view = self._append_single_quarter_rows(view)
        view["rnd_expense_ratio"] = (
            pd.to_numeric(view["operating_expense_rnd_expenses"], errors="coerce")
            / pd.to_numeric(view["total_operating_revenue"], errors="coerce")
            * 100
        )
        view["accounts_receivable_ratio"] = (
            pd.to_numeric(view["asset_accounts_receivable"], errors="coerce")
            / pd.to_numeric(view["total_operating_revenue"], errors="coerce")
            * 100
        )
        view["inventory_turnover_ratio"] = (
            pd.to_numeric(view["operating_expense_selling_expenses"], errors="coerce")
            / pd.to_numeric(view["asset_inventory"], errors="coerce")
        )
        return view

    def _append_single_quarter_rows(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty or "report_period" not in dataframe.columns or "report_year" not in dataframe.columns:
            return dataframe
        derivable_columns = [column for column in DERIVABLE_SINGLE_QUARTER_COLUMNS if column in dataframe.columns]
        if not derivable_columns:
            return dataframe

        new_rows: list[dict[str, Any]] = []
        work = dataframe.copy()
        work["report_year"] = pd.to_numeric(work["report_year"], errors="coerce")
        work = work.dropna(subset=["stock_code", "report_year", "report_period"]).copy()
        work["report_year"] = work["report_year"].astype(int)

        for (stock_code, report_year), group in work.groupby(["stock_code", "report_year"]):
            records = group.to_dict(orient="records")
            period_map = {
                str(row["report_period"])[4:]: row
                for row in records
                if str(row.get("report_period", "")).startswith(str(report_year))
            }
            existing_periods = {
                str(row.get("report_period", ""))
                for row in records
                if str(row.get("report_period", "")).startswith(str(report_year))
            }
            for target_suffix, base_suffix, previous_suffix in [("Q2", "H1", "Q1"), ("Q4", "FY", "Q3")]:
                target_period = f"{report_year}{target_suffix}"
                if target_period in existing_periods:
                    continue
                base_row = period_map.get(base_suffix)
                previous_row = period_map.get(previous_suffix)
                if not base_row or not previous_row:
                    continue
                new_row = {column: pd.NA for column in dataframe.columns}
                new_row["stock_code"] = stock_code
                if "stock_abbr" in dataframe.columns:
                    new_row["stock_abbr"] = base_row.get("stock_abbr") or previous_row.get("stock_abbr")
                new_row["report_period"] = target_period
                new_row["report_year"] = report_year
                for column in derivable_columns:
                    base_value = pd.to_numeric(pd.Series([base_row.get(column)]), errors="coerce").iloc[0]
                    previous_value = pd.to_numeric(pd.Series([previous_row.get(column)]), errors="coerce").iloc[0]
                    if pd.isna(base_value) or pd.isna(previous_value):
                        continue
                    new_row[column] = float(base_value - previous_value)
                if any(pd.notna(new_row.get(column)) for column in derivable_columns):
                    new_rows.append(new_row)

        if not new_rows:
            return dataframe
        return pd.concat([dataframe, pd.DataFrame(new_rows)], ignore_index=True, sort=False)

    def _write_query_cache(self) -> None:
        conn = sqlite3.connect(self.config.query_cache_db)
        try:
            self.view_df.to_sql("financials_view", conn, if_exists="replace", index=False)
        finally:
            conn.close()

    def _schema_text(self) -> str:
        columns = ", ".join(self.view_df.columns.tolist())
        return (
            "Use only the SQLite table `financials_view`.\n"
            f"Available columns: {columns}\n"
            "Helpful aliases already available in financials_view:\n"
            "- total_assets = 资产总计\n"
            "- total_equity = 股东权益总额\n"
            "- accounts_receivable = 应收账款\n"
            "- accounts_receivable_ratio = 应收账款占营业总收入比例\n"
            "- operating_cost = 营业成本\n"
            "- selling_expenses = 销售费用\n"
            "- administrative_expenses = 管理费用\n"
            "- financial_expenses = 财务费用\n"
            "- taxes_and_surcharges = 税金及附加\n"
            "Report period format uses values like 2024FY, 2025Q3, 2025H1, 2025Q2, 2025Q4.\n"
            "Q2/Q4 rows may be derived from cumulative disclosures when available."
        )

    def _write_chunk_manifest(self) -> None:
        path = self.config.chunk_dir / "report_chunks.json"
        path.write_text(json.dumps(self.chunk_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_metadata_lookup(self) -> None:
        path = self.config.chunk_dir / "report_metadata_lookup.json"
        path.write_text(json.dumps(self.report_metadata_lookup, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_chunk_quality_samples(self, samples: list[dict[str, Any]]) -> None:
        path = self.config.chunk_dir / "chunk_quality_samples.json"
        path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_vector_store_meta(self) -> None:
        self.vector_store.save_index_meta(
            {
                "index_type": self.vector_store._preferred_index_type(),
                "embedding_provider": "openai-compatible" if self.embedding_client else "not_configured",
                "embedding_model": self.config.embedding_model or "",
                "chunk_count": len(self.chunk_manifest),
                "index_status": "metadata_only",
            }
        )

    def _load_or_build_chunk_manifest(
        self,
        stock_report_info: pd.DataFrame,
        industry_report_info: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        manifest_path = self.config.chunk_dir / "report_chunks.json"
        if manifest_path.exists():
            try:
                return json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return build_report_chunk_manifest(
            stock_reports=stock_report_info,
            industry_reports=industry_report_info,
            stock_report_dir=self.config.stock_report_dir,
            industry_report_dir=self.config.industry_report_dir,
            field_descriptions=self.report_field_descriptions,
            chunk_size_chars=self.config.chunk_size_chars,
            chunk_overlap_chars=self.config.chunk_overlap_chars,
            max_pages_per_report=self.config.max_pages_per_report,
        )

    def _build_chunk_lookup(self, chunks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        lookup: dict[str, list[dict[str, Any]]] = {}
        for chunk in chunks:
            metadata_ref = str(chunk.get("metadata_ref", "") or "").strip()
            if not metadata_ref:
                continue
            lookup.setdefault(metadata_ref, []).append(chunk)
        return lookup

    def _question_terms(self, question: str) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", str(question or ""))
        stopwords = {"什么", "哪些", "如何", "为什么", "一下", "情况", "公司", "企业", "他们", "这些", "上述", "还是", "下降", "增长", "分析"}
        unique: list[str] = []
        for token in tokens:
            if token in stopwords or token in unique:
                continue
            unique.append(token)
        return unique

    def _select_reference_chunk(self, evidence: dict[str, Any], *, question: str = "") -> dict[str, Any]:
        if evidence.get("text") and (evidence.get("page") or evidence.get("page_start")):
            return evidence
        metadata_ref = str(evidence.get("metadata_ref", "") or "").strip()
        candidates = self.chunks_by_metadata_ref.get(metadata_ref, []) if metadata_ref else []
        if not candidates:
            return {}
        question_terms = self._question_terms(question)
        best_score = float("-inf")
        best_chunk: dict[str, Any] = candidates[0]
        for chunk in candidates:
            score = 0.0
            text = str(chunk.get("text", "") or "")
            chunk_type = str(chunk.get("chunk_type", "") or "")
            company_or_industry = str(evidence.get("company_or_industry", "") or "")
            if chunk_type == "body":
                score += 2.0
            if chunk.get("section_title"):
                score += 0.5
            if len(text) < 30:
                score -= 1.5
            if company_or_industry:
                if company_or_industry in text:
                    score += 2.0
                else:
                    score -= 0.8
            for term in question_terms:
                if term in text:
                    score += 1.0
            if chunk.get("figure_table_refs"):
                score += 0.2
            if score > best_score:
                best_score = score
                best_chunk = chunk
        return best_chunk

    def _select_visual_reference_chunk(
        self,
        evidence: dict[str, Any],
        *,
        reference_chunk: dict[str, Any] | None = None,
        question: str = "",
    ) -> dict[str, Any]:
        metadata_ref = str(evidence.get("metadata_ref", "") or "").strip()
        candidates = self.chunks_by_metadata_ref.get(metadata_ref, []) if metadata_ref else []
        visual_candidates = [chunk for chunk in candidates if str(chunk.get("chunk_type", "") or "") == "visual_caption"]
        if not visual_candidates:
            return {}
        question_terms = self._question_terms(question)
        reference_chunk = reference_chunk or {}
        reference_page = int(
            reference_chunk.get("page_start")
            or reference_chunk.get("page")
            or evidence.get("page_start")
            or evidence.get("page")
            or 0
        )
        company_or_industry = str(evidence.get("company_or_industry", "") or "")
        best_score = float("-inf")
        best_chunk: dict[str, Any] = {}
        for chunk in visual_candidates:
            score = 0.0
            text = str(chunk.get("text", "") or "")
            caption = self._format_visual_caption(chunk.get("visual_caption"))
            page = int(chunk.get("page_start") or chunk.get("page") or 0)
            if caption:
                score += 1.0
            if company_or_industry and (company_or_industry in text or company_or_industry in caption):
                score += 1.5
            for term in question_terms:
                if term and (term in text or term in caption):
                    score += 1.0
            if reference_page and page:
                gap = abs(reference_page - page)
                if gap == 0:
                    score += 1.2
                elif gap <= 2:
                    score += 0.6
                elif gap <= 4:
                    score += 0.2
            if score > best_score:
                best_score = score
                best_chunk = chunk
        return best_chunk if best_score >= 1.0 else {}

    def _derive_answer_constraints(
        self,
        question: str,
        query_plan: dict[str, Any],
        query_result: pd.DataFrame,
    ) -> dict[str, Any]:
        metric_name = ""
        metrics = query_plan.get("metrics", []) or []
        if metrics:
            metric_name = str(metrics[0])
        columns = set(query_result.columns.tolist())
        if not metric_name:
            if {"current_total_profit", "total_profit"} & columns:
                metric_name = "利润总额"
            elif {"total_operating_revenue"} & columns:
                metric_name = "营业总收入"
            elif {"net_profit"} & columns:
                metric_name = "净利润"
        return {
            "question": question,
            "primary_metric_name": metric_name,
            "row_count": int(len(query_result)),
            "result_columns": query_result.columns.tolist(),
            "must_preserve_metric_name": bool(metric_name),
            "must_explain_empty_evidence": True,
            "must_list_entities_when_multiple_rows": len(query_result) > 1,
            "has_aggregate_only_rows": any(
                str(col).lower().startswith(("avg_", "min_", "max_", "sum_", "count_"))
                for col in query_result.columns.tolist()
            ),
            "forbid_using_aggregate_rows_as_company_common_points": bool(
                query_result.columns.tolist()
                and all(
                    str(col).lower().startswith(("avg_", "min_", "max_", "sum_", "count_"))
                    or str(col) in {"report_period", "stock_abbr", "stock_code"}
                    for col in query_result.columns.tolist()
                )
            ),
            "must_explicitly_distinguish_revenue_terms": any(
                token in question for token in ["主营业务收入", "营业总收入", "营业收入"]
            ),
            "prefer_qualitative_evidence_for_reason_analysis": any(
                token in question for token in ["为什么", "原因", "驱动"]
            ),
            "ignore_suspicious_zero_growth_fields": self._has_suspicious_zero_growth_fields(query_result),
            "numeric_unit_hint": "数据库金额口径默认为万元；如转成亿元表述，必须明确说明换算关系。",
        }

    def _normalize_retrieval_plan(
        self,
        question: str,
        retrieval_plan: dict[str, Any],
        parsed_slots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parsed_slots = parsed_slots or {}
        plan = dict(retrieval_plan or {})
        companies = list(plan.get("companies", []) or parsed_slots.get("companies", []) or [])
        focus_topics = list(plan.get("focus_topics", []) or parsed_slots.get("focus_topics", []) or [])
        focus_topics = self._augment_focus_topics(question, focus_topics)
        intent_type = str(parsed_slots.get("intent_type", "") or "")
        retrieval_must_run = any(
            token in question
            for token in [
                "结合研报",
                "结合个股研报",
                "结合行业研报",
                "检索研报",
                "研报中",
                "提取研报",
                "提取研报观点",
                "提取观点",
                "观点",
                "风险预警",
                "说明",
            ]
        )
        if any(token in question for token in ["未来", "趋势", "预测", "价格波动", "中药材价格"]):
            companies = []
        source_scope = self._normalize_source_scope(question, plan.get("source_scope"), companies, focus_topics)
        retrieval_mode = self._normalize_retrieval_mode(plan.get("retrieval_mode"))
        top_k = int(plan.get("top_k", 5) or 5)
        needs_retrieval = bool(plan.get("needs_retrieval", parsed_slots.get("needs_retrieval", True)))
        if intent_type in {"sql_only", "sql_chart"}:
            needs_retrieval = retrieval_must_run
            top_k = max(top_k, 8) if retrieval_must_run else 0
        elif intent_type == "industry_open_analysis":
            source_scope = "industry"
            top_k = max(top_k, 8)
        elif intent_type == "causal_analysis":
            top_k = max(top_k, 8)
        if retrieval_must_run:
            needs_retrieval = True
            top_k = max(top_k, 8)
        if any(token in question for token in ["为什么", "原因", "驱动"]) and companies:
            top_k = max(top_k, 8)
        plan.update(
            {
                "question": question,
                "companies": companies,
                "focus_topics": focus_topics,
                "needs_retrieval": needs_retrieval,
                "top_k": top_k,
                "source_scope": source_scope,
                "retrieval_mode": retrieval_mode,
            }
        )
        return plan

    def _fallback_retrieval_plan(self, retrieval_plan: dict[str, Any]) -> dict[str, Any] | None:
        question = str(retrieval_plan.get("question", "") or "")
        companies = list(retrieval_plan.get("companies", []) or [])
        if not companies:
            return None
        if not any(token in question for token in ["为什么", "原因", "驱动", "变化", "提升", "上升"]):
            return None
        fallback_topics = self._augment_focus_topics(question, list(retrieval_plan.get("focus_topics", []) or []))
        fallback_topics.extend(["收入增长", "业绩增长", "产品", "渠道", "品牌", "业务结构", "市场拓展", "并购整合"])
        dedup_topics: list[str] = []
        for topic in fallback_topics:
            if topic and topic not in dedup_topics:
                dedup_topics.append(topic)
        return {
            "question": question,
            "companies": companies,
            "focus_topics": dedup_topics[:12],
            "needs_retrieval": True,
            "top_k": max(int(retrieval_plan.get("top_k", 5) or 5), 8),
            "source_scope": "hybrid",
            "retrieval_mode": "hybrid" if self.embedding_client else "metadata",
        }

    def _normalize_source_scope(
        self,
        question: str,
        raw_scope: Any,
        companies: list[str],
        focus_topics: list[str],
    ) -> str:
        if isinstance(raw_scope, list):
            scope_tokens = [str(item).strip().lower() for item in raw_scope if str(item).strip()]
        else:
            scope_tokens = [str(raw_scope or "").strip().lower()]
        valid = {"stock", "industry", "hybrid"}
        for token in scope_tokens:
            if token in valid:
                return token
        joined = " ".join(scope_tokens)
        if any(token in joined for token in ["company_announcement", "annual_report", "stock_report", "research_report"]):
            if companies and any(token in question for token in ["为什么", "原因", "驱动", "变化", "上升", "下降"]):
                return "hybrid"
            return "stock" if companies else "hybrid"
        if any(token in joined for token in ["industry_report", "sector", "行业", "板块"]):
            return "industry" if not companies else "hybrid"
        if any(token in question for token in ["结合个股研报", "个股研报", "业绩预告", "FDA", "资产重组", "海外市场拓展"]):
            return "stock" if companies else "hybrid"
        if any(token in question for token in ["结合行业研报", "政策研报", "行业研报", "行业周报", "投资策略", "行业趋势", "景气度"]):
            return "industry" if not companies else "hybrid"
        if not companies and any(token in question for token in ["新品上市周期", "研发投入结构", "大健康产品布局", "大健康"]):
            return "industry"
        if companies:
            if any(token in question for token in ["行业", "景气度", "关系", "影响", "对比", "趋势"]):
                return "hybrid"
            if any(topic for topic in focus_topics if any(flag in topic for flag in ["行业", "板块", "景气度", "趋势"])):
                return "hybrid"
            return "stock"
        return "industry" if any(token in question for token in ["行业", "板块"]) else "hybrid"

    def _normalize_retrieval_mode(self, raw_mode: Any) -> str:
        mode = str(raw_mode or "").strip().lower()
        if mode in {"metadata", "vector", "hybrid"}:
            return mode
        if mode in {"semantic_search", "semantic", "embedding", "dense"}:
            return "hybrid" if self.embedding_client else "metadata"
        if mode in {"keyword", "bm25"}:
            return "metadata"
        return "hybrid" if self.embedding_client else "metadata"

    @staticmethod
    def _augment_focus_topics(question: str, focus_topics: list[str]) -> list[str]:
        augmented: list[str] = []
        for topic in focus_topics or []:
            topic_str = str(topic).strip()
            if topic_str and topic_str not in augmented:
                augmented.append(topic_str)
        if any(token in question for token in ["为什么", "原因", "驱动"]):
            for token in ["增长驱动", "业务结构", "市场拓展", "产品线", "品牌", "渠道"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["海外市场拓展", "海外拓展", "出海"]):
            for token in ["海外市场拓展", "海外拓展", "出海", "国际化", "海外业务", "出口"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["人工智能", "产业升级", "AI"]):
            for token in ["人工智能", "产业升级", "AI", "智能化", "数字化", "信息化"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["资产重组", "并购重组"]):
            for token in ["资产重组", "重大资产重组", "并购", "重组", "控制权变更", "股权转让"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["FDA", "认证"]):
            for token in ["FDA", "FDA认证", "认证", "海外注册", "国际认证"]:
                if token not in augmented:
                    augmented.append(token)
        if "业绩预告" in question:
            for token in ["业绩预告", "预告", "净利润预告", "业绩快报"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["主营业务收入", "营业总收入", "营业收入"]):
            for token in ["主营业务收入", "营业总收入", "收入增长"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["主营业务类型", "业务类型", "成本控制", "成本结构", "营业总成本", "营业成本", "销售费用", "管理费用", "研发费用"]):
            for token in ["主营业务", "主营业务类型", "业务类型", "成本控制", "成本结构", "销售费用", "研发费用", "中药", "创新药"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["中药材", "价格波动", "价格趋势", "趋势", "供需", "库存", "种植", "气候"]):
            for token in ["中药材", "价格", "价格波动", "趋势", "供需", "库存", "种植", "气候", "政策", "中药"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["偿债风险", "偿债能力", "流动比率"]):
            for token in ["偿债风险", "偿债能力", "流动比率", "短期偿债", "现金流", "负债"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["投资项目", "投资性现金流"]):
            for token in ["投资项目", "投资说明", "资本开支", "投资性现金流", "扩产"]:
                if token not in augmented:
                    augmented.append(token)
        if any(token in question for token in ["大健康", "新品上市周期", "研发投入结构", "种植基地", "订单农业", "基地共建"]):
            for token in [
                "大健康",
                "新品上市",
                "新品上市周期",
                "新药上市",
                "研发投入结构",
                "研发投入",
                "研发费用",
                "研发强度",
                "研发管线",
                "创新管线",
                "种植基地",
                "订单农业",
                "基地共建",
            ]:
                if token not in augmented:
                    augmented.append(token)
        return augmented

    @staticmethod
    def _is_simple_fact_question(question: str) -> bool:
        simple_tokens = ["有哪些", "是什么", "多少", "列出", "给出", "哪几家", "哪家", "哪只", "是哪一个"]
        complex_tokens = ["为什么", "原因", "共同点", "关系", "影响", "分析", "比较", "趋势", "驱动"]
        return any(token in question for token in simple_tokens) and not any(token in question for token in complex_tokens)

    @staticmethod
    def _question_requires_chart(question: str) -> bool:
        return any(token in question for token in ["可视化", "绘图", "画图", "图表", "柱状图", "折线图", "饼图", "雷达图", "散点图", "直方图", "箱线图"])

    @staticmethod
    def _top_scores_are_clearly_separated(evidences: list[dict[str, Any]]) -> bool:
        scores: list[float] = []
        for item in evidences[:5]:
            try:
                scores.append(float(item.get("score", 0.0)))
            except Exception:
                scores.append(0.0)
        if len(scores) < 3:
            return True
        top1, top2, top3 = scores[0], scores[1], scores[2]
        if top1 <= 0:
            return False
        return (top1 - top2 >= 0.18 and top2 - top3 >= 0.08) or (top1 >= top2 * 1.25 and top2 >= top3 * 1.1)

    def should_skip_retrieval(
        self,
        question: str,
        query_plan: dict[str, Any] | None,
        parsed_slots: dict[str, Any] | None,
        turn_index: int,
    ) -> bool:
        if turn_index != 0:
            return False
        query_plan = query_plan or {}
        parsed_slots = parsed_slots or {}
        if not bool(query_plan.get("needs_sql")):
            return False
        if not self._question_requires_chart(question):
            return False
        if any(token in question for token in ["为什么", "原因", "依据", "判断依据", "关系", "共同点", "影响", "分析"]):
            return False
        metrics = list(parsed_slots.get("metrics", []) or query_plan.get("metrics", []) or [])
        if not metrics:
            return False
        return True

    def _can_short_circuit_without_evidence(
        self,
        question: str,
        query_plan: dict[str, Any] | None,
        query_result: pd.DataFrame,
    ) -> bool:
        query_plan = query_plan or {}
        if self._question_requires_chart(question) and bool(query_plan.get("needs_sql")):
            return True
        if self._is_simple_fact_question(question):
            return True
        if len(query_result) > 0 and not any(
            token in question for token in ["为什么", "原因", "关系", "共同点", "影响", "分析", "判断依据", "依据"]
        ):
            return True
        return False

    def _sql_cache_path(self, sql: str) -> Path:
        digest = hashlib.sha1(sql.encode("utf-8")).hexdigest()
        return self.sql_cache_dir / f"{digest}.json"

    def _retrieval_cache_path(self, retrieval_plan: dict[str, object]) -> Path:
        payload = json.dumps(retrieval_plan, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return self.retrieval_cache_dir / f"{digest}.json"

    @staticmethod
    def _load_json_cache(path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _write_json_cache(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def sanitize_query_result_for_answer(self, question: str, query_result: pd.DataFrame) -> pd.DataFrame:
        if query_result.empty:
            return query_result
        sanitized = query_result.copy()
        if any(token in question for token in ["为什么", "原因", "驱动", "变化"]) and self._has_suspicious_zero_growth_fields(sanitized):
            drop_cols = [
                col
                for col in sanitized.columns
                if any(token in str(col).lower() for token in ["yoy_growth", "qoq_growth", "_growth"])
            ]
            if drop_cols:
                sanitized = sanitized.drop(columns=drop_cols, errors="ignore")
        return sanitized

    @staticmethod
    def _format_visual_caption(value: Any) -> str:
        if isinstance(value, dict):
            label = str(value.get("label", "") or "").strip()
            caption = str(value.get("caption", "") or "").strip()
            return f"{label}：{caption}" if label and caption else label or caption
        return str(value or "").strip()

    def _to_reference_relative_path(self, path_value: Any) -> str:
        path_str = str(path_value or "").strip()
        if not path_str:
            return ""
        path = Path(path_str)
        try:
            relative = path.relative_to(self.config.base_dir / "正式数据")
            return f"./{relative.as_posix()}"
        except Exception:
            try:
                relative = path.relative_to(self.config.base_dir)
                return f"./{relative.as_posix()}"
            except Exception:
                return path_str

    @staticmethod
    def _normalize_threshold_literals(sql: str, query_plan: dict[str, Any]) -> str:
        threshold = query_plan.get("threshold")
        if threshold in (None, ""):
            return sql
        try:
            threshold_value = float(threshold)
        except Exception:
            return sql
        if threshold_value <= 0:
            return sql
        metric_fields = [
            "total_operating_revenue",
            "net_profit",
            "total_profit",
            "asset_cash_and_cash_equivalents",
            "liability_short_term_loans",
            "equity_unappropriated_profit",
            "operating_cf_net_amount",
            "investing_cf_net_amount",
            "financing_cf_net_amount",
        ]
        normalized_sql = sql
        replacement = f"{threshold_value:.6f}".rstrip("0").rstrip(".")
        for field in metric_fields:
            pattern = re.compile(
                rf"({field}\s*(?:>=|<=|>|<|=)\s*)([0-9]+(?:\.[0-9]+)?)",
                flags=re.IGNORECASE,
            )

            def _replace(match: re.Match[str]) -> str:
                literal = float(match.group(2))
                if literal > threshold_value * 100:
                    return f"{match.group(1)}{replacement}"
                return match.group(0)

            normalized_sql = pattern.sub(_replace, normalized_sql)
        return normalized_sql

    def summarize_index_status(self) -> dict[str, Any]:
        index_meta = self.vector_store.load_index_meta()
        progress = self.vector_store.load_progress()
        total_chunks = len(self.chunk_manifest)
        stock_chunk_count = sum(1 for chunk in self.chunk_manifest if chunk.get("source_type") == "stock")
        industry_chunk_count = sum(1 for chunk in self.chunk_manifest if chunk.get("source_type") == "industry")
        pdf_refs = {
            str(chunk.get("metadata_ref"))
            for chunk in self.chunk_manifest
            if chunk.get("content_source") == "pdf_page" and chunk.get("metadata_ref")
        }
        fallback_refs = {
            str(chunk.get("metadata_ref"))
            for chunk in self.chunk_manifest
            if chunk.get("content_source") == "metadata_fallback" and chunk.get("metadata_ref")
        }
        completed_chunks = int(progress.get("next_index", 0) or 0)
        if not completed_chunks and index_meta.get("index_status") == "ready":
            completed_chunks = int(index_meta.get("chunk_count", total_chunks) or total_chunks)
        chunk_quality_samples = self._sample_chunk_quality()
        self._write_chunk_quality_samples(chunk_quality_samples)
        return {
            "chunk_manifest": str(self.config.chunk_dir / "report_chunks.json"),
            "metadata_lookup": str(self.config.chunk_dir / "report_metadata_lookup.json"),
            "chunk_quality_samples_path": str(self.config.chunk_dir / "chunk_quality_samples.json"),
            "vector_store_meta": str(self.config.vector_store_dir / "index_meta.json"),
            "index_meta": index_meta,
            "index_progress": progress,
            "chunk_count": total_chunks,
            "stock_report_count": self.stock_report_count,
            "industry_report_count": self.industry_report_count,
            "stock_chunk_count": stock_chunk_count,
            "industry_chunk_count": industry_chunk_count,
            "pdf_extracted_report_count": len(pdf_refs),
            "metadata_fallback_report_count": len(fallback_refs),
            "completed_chunk_count": completed_chunks,
            "remaining_chunk_count": max(0, total_chunks - completed_chunks),
            "next_resume_index": int(progress.get("next_index", 0) or 0),
            "field_description_sheets": sorted(self.report_field_descriptions.keys()),
            "chunk_quality_samples": chunk_quality_samples,
        }

    def _sample_chunk_quality(self) -> list[dict[str, Any]]:
        desired_pairs = [
            ("stock", "body"),
            ("stock", "visual_caption"),
            ("stock", "metadata_fallback"),
            ("industry", "body"),
            ("industry", "visual_caption"),
            ("industry", "metadata_fallback"),
        ]
        selected: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for chunk in self.chunk_manifest:
            source_type = str(chunk.get("source_type", "") or "")
            chunk_type = str(chunk.get("chunk_type", "") or "")
            by_pair.setdefault((source_type, chunk_type), []).append(chunk)

        def _format(chunk: dict[str, Any]) -> dict[str, Any]:
            text = str(chunk.get("text", "") or "")
            return {
                "chunk_id": str(chunk.get("chunk_id", "") or ""),
                "source_type": str(chunk.get("source_type", "") or ""),
                "chunk_type": str(chunk.get("chunk_type", "") or ""),
                "title": str(chunk.get("title", "") or ""),
                "company": str(chunk.get("company", "") or ""),
                "industry": str(chunk.get("industry", "") or ""),
                "page_start": int(chunk.get("page_start", 0) or 0),
                "page_end": int(chunk.get("page_end", 0) or 0),
                "section_title": str(chunk.get("section_title", "") or ""),
                "subsection_title": str(chunk.get("subsection_title", "") or ""),
                "figure_table_refs": chunk.get("figure_table_refs", []) or [],
                "content_source": str(chunk.get("content_source", "") or ""),
                "char_count": len(text),
                "text_preview": text[:220],
            }

        for pair in desired_pairs:
            candidates = by_pair.get(pair, [])
            if not candidates:
                continue
            chunk = candidates[0]
            chunk_id = str(chunk.get("chunk_id", "") or "")
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            selected.append(_format(chunk))

        if len(selected) < 6:
            for chunk in self.chunk_manifest:
                chunk_id = str(chunk.get("chunk_id", "") or "")
                if chunk_id in seen_chunk_ids:
                    continue
                selected.append(_format(chunk))
                seen_chunk_ids.add(chunk_id)
                if len(selected) >= 6:
                    break
        return selected

    @staticmethod
    def _deduplicate_evidences(evidences: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in evidences:
            key = (
                str(item.get("title", "")),
                str(item.get("relative_path", "") or item.get("path", "")),
                str(item.get("source_type", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _evidence_to_rerank_text(item: dict[str, Any]) -> str:
        parts = [
            str(item.get("title", "") or ""),
            str(item.get("company_or_industry", "") or item.get("company", "") or item.get("industry", "") or ""),
            str(item.get("organization", "") or ""),
            str(item.get("snippet", "") or ""),
            str(item.get("text", "") or ""),
        ]
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _has_suspicious_zero_growth_fields(query_result: pd.DataFrame) -> bool:
        if query_result.empty:
            return False
        growth_cols = [
            col
            for col in query_result.columns
            if any(token in str(col).lower() for token in ["yoy_growth", "qoq_growth", "_growth"])
        ]
        if not growth_cols:
            return False
        direct_value_cols = [
            col
            for col in query_result.columns
            if any(token in str(col).lower() for token in ["revenue", "profit", "income", "total_operating_revenue", "total_profit"])
            and col not in growth_cols
        ]
        if not direct_value_cols:
            return False
        for col in growth_cols:
            series = pd.to_numeric(query_result[col], errors="coerce").dropna()
            if not series.empty and (series.abs() <= 1e-9).all():
                return True
        return False

    def _prepare_vector_index(self) -> None:
        if not self.embedding_client:
            self._write_vector_store_meta()
            return
        if not self.config.build_index_on_start:
            current_meta = self.vector_store.load_index_meta()
            persisted_chunks = self.vector_store.load_chunks()
            has_persisted_faiss = self.vector_store.faiss_index_path.exists()
            if self.vector_store.has_index():
                if current_meta:
                    current_meta.setdefault("index_status", "ready")
                    self.vector_store.save_index_meta(current_meta)
                return
            if persisted_chunks and has_persisted_faiss:
                repaired_meta = dict(current_meta)
                repaired_meta.setdefault("index_type", self.vector_store._preferred_index_type())
                repaired_meta.setdefault(
                    "embedding_provider",
                    "openai-compatible" if self.embedding_client else "not_configured",
                )
                repaired_meta.setdefault("embedding_model", self.config.embedding_model or "")
                repaired_meta["chunk_count"] = int(repaired_meta.get("chunk_count", len(persisted_chunks)) or len(persisted_chunks))
                repaired_meta["index_status"] = "ready"
                self.vector_store.save_index_meta(repaired_meta)
            else:
                self._write_vector_store_meta()
            return
        indexed_chunk_count = min(self.config.index_limit or len(self.chunk_manifest), len(self.chunk_manifest))
        current_meta = self.vector_store.load_index_meta()
        if self.vector_store.has_index() and int(current_meta.get("chunk_count", 0) or 0) == indexed_chunk_count:
            meta = self.vector_store.load_index_meta()
            meta.setdefault("index_status", "ready")
            self.vector_store.save_index_meta(meta)
            return
        chunks_for_index = self.chunk_manifest[:indexed_chunk_count]
        try:
            self.vector_store.build_index_resumable(
                chunks_for_index,
                self.embedding_client,
                embedding_model=self.config.embedding_model or "",
                batch_size=self.config.embedding_batch_size,
                pause_seconds=self.config.embedding_batch_pause_seconds,
                max_batches=self.config.embedding_max_batches_per_run,
                progress_callback=self.index_progress_callback,
            )
        except Exception as exc:
            progress = self.vector_store.load_progress()
            self.vector_store.save_index_meta(
                {
                    "index_type": self.vector_store._preferred_index_type(),
                    "embedding_provider": "openai-compatible",
                    "embedding_model": self.config.embedding_model or "",
                    "chunk_count": indexed_chunk_count,
                    "index_status": "build_failed",
                    "error": str(exc),
                    "next_index": progress.get("next_index", 0),
                    "completed_batches": progress.get("completed_batches", 0),
                }
            )


__all__ = ["Task3Runtime"]
