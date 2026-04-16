from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

import pandas as pd
from sqlalchemy import create_engine

from ..config import Task3LangGraphConfig
from ..schemas import QuestionRecord
from ..services import (
    OpenAICompatibleClient,
    OpenAICompatibleEmbeddingClient,
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
        self.config.vector_store_dir.mkdir(parents=True, exist_ok=True)
        self.config.chunk_dir.mkdir(parents=True, exist_ok=True)

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
        self.chunk_manifest = self._load_or_build_chunk_manifest(
            stock_report_info=stock_report_info,
            industry_report_info=industry_report_info,
        )
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
        return default_plan

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
        return default_plan

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
        if context_rows:
            user_prompt += f"Previous turn result rows: {json.dumps(context_rows[:12], ensure_ascii=False)}\n"
        if previous_sql or previous_error:
            user_prompt += f"Previous SQL: {previous_sql or ''}\nPrevious error: {previous_error or ''}\nPlease repair it.\n"
        payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
        sql = str(payload.get("sql", "")).strip()
        if sql:
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
        conn = sqlite3.connect(self.config.query_cache_db)
        try:
            return pd.read_sql_query(sql, conn)
        finally:
            conn.close()

    def retrieve_evidence(self, retrieval_plan: dict[str, object]) -> list[dict[str, Any]]:
        if not retrieval_plan.get("needs_retrieval", True):
            return []
        return self.retriever.retrieve(retrieval_plan)

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
        mode = retrieval_mode or ("hybrid" if self.embedding_client else "metadata")
        plan = {
            "question": question,
            "companies": companies or [],
            "focus_topics": focus_topics or [],
            "needs_retrieval": True,
            "top_k": top_k,
            "source_scope": source_scope,
            "retrieval_mode": mode,
        }
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

    def generate_answer(
        self,
        question: str,
        sql: str,
        query_result: pd.DataFrame,
        evidences: list[dict[str, Any]],
    ) -> str:
        system_prompt = self.prompt_manager.load("answer_generation_system")
        user_prompt = (
            f"Question: {question}\n"
            f"SQL: {sql}\n"
            f"Rows: {query_result.head(20).to_json(force_ascii=False, orient='records')}\n"
            f"Evidences: {json.dumps(evidences[:5], ensure_ascii=False)}\n"
            "请直接给出中文回答。"
        )
        return self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()

    def enrich_reference(self, evidence: dict[str, Any]) -> dict[str, Any]:
        metadata_ref = str(evidence.get("metadata_ref", "") or "")
        metadata = self.report_metadata_lookup.get(metadata_ref, {}) if metadata_ref else {}
        return {
            "title": evidence.get("title", "") or metadata.get("title", ""),
            "path": evidence.get("relative_path", "") or metadata.get("path", ""),
            "source_type": evidence.get("source_type", "") or metadata.get("source_type", ""),
            "publish_date": evidence.get("publish_date", "") or metadata.get("publish_date", ""),
            "organization": evidence.get("organization", "") or metadata.get("organization", ""),
            "company_or_industry": evidence.get("company_or_industry", "")
            or metadata.get("company")
            or metadata.get("industry", ""),
            "rating_current": metadata.get("rating_current", ""),
        }

    def generate_clarification(self, question: str, missing_slots: list[str]) -> str:
        try:
            system_prompt = self.prompt_manager.load("clarification_system")
            user_prompt = f"Question: {question}\nMissing slots: {missing_slots}"
            return self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()
        except Exception:
            return "请补充继续分析所需的关键信息。"

    def _build_view(self) -> pd.DataFrame:
        key_cols = ["stock_code", "stock_abbr", "report_period", "report_year"]
        kpi = pd.read_sql_table("core_performance_indicators_sheet", self.engine)
        bal = pd.read_sql_table("balance_sheet", self.engine)
        cash = pd.read_sql_table("cash_flow_sheet", self.engine)
        inc = pd.read_sql_table("income_sheet", self.engine)

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
        inc_subset = inc[
            key_cols
            + [
                "net_profit",
                "net_profit_yoy_growth",
                "total_operating_revenue",
                "operating_revenue_yoy_growth",
                "total_profit",
                "operating_expense_rnd_expenses",
                "operating_expense_selling_expenses",
            ]
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
        view = view.merge(bal[key_cols + ["asset_liability_ratio", "asset_cash_and_cash_equivalents", "liability_short_term_loans", "equity_unappropriated_profit", "asset_inventory"]], on=key_cols, how="left")
        view = view.merge(cash[key_cols + ["operating_cf_net_amount", "investing_cf_net_amount", "financing_cf_net_amount", "net_cash_flow"]], on=key_cols, how="left")

        view["total_operating_revenue"] = view["income_total_operating_revenue"].combine_first(view["kpi_total_operating_revenue"])
        view["operating_revenue_yoy_growth"] = view["income_operating_revenue_yoy_growth"].combine_first(view["kpi_operating_revenue_yoy_growth"])
        view["operating_revenue_qoq_growth"] = view["kpi_operating_revenue_qoq_growth"]
        view["net_profit"] = view["income_net_profit"].combine_first(view["kpi_net_profit"])
        view["net_profit_yoy_growth"] = view["income_net_profit_yoy_growth"].combine_first(view["kpi_net_profit_yoy_growth"])
        view["net_profit_qoq_growth"] = view["kpi_net_profit_qoq_growth"]
        view["rnd_expense_ratio"] = (
            pd.to_numeric(view["operating_expense_rnd_expenses"], errors="coerce")
            / pd.to_numeric(view["total_operating_revenue"], errors="coerce")
            * 100
        )
        view["inventory_turnover_ratio"] = (
            pd.to_numeric(view["operating_expense_selling_expenses"], errors="coerce")
            / pd.to_numeric(view["asset_inventory"], errors="coerce")
        )
        return view

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
            "Report period format uses values like 2024FY, 2025Q3, 2025H1."
        )

    def _write_chunk_manifest(self) -> None:
        path = self.config.chunk_dir / "report_chunks.json"
        path.write_text(json.dumps(self.chunk_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_metadata_lookup(self) -> None:
        path = self.config.chunk_dir / "report_metadata_lookup.json"
        path.write_text(json.dumps(self.report_metadata_lookup, ensure_ascii=False, indent=2), encoding="utf-8")

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
        return {
            "chunk_manifest": str(self.config.chunk_dir / "report_chunks.json"),
            "metadata_lookup": str(self.config.chunk_dir / "report_metadata_lookup.json"),
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
        }

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

    def _prepare_vector_index(self) -> None:
        if not self.embedding_client:
            self._write_vector_store_meta()
            return
        if not self.config.build_index_on_start:
            current_meta = self.vector_store.load_index_meta()
            if not self.vector_store.has_index():
                self._write_vector_store_meta()
            elif current_meta:
                current_meta.setdefault("index_status", "ready")
                self.vector_store.save_index_meta(current_meta)
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
