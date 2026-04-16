from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from ..schemas import RetrievedEvidence
from .report_metadata import normalize_report_metadata


class MetadataRetriever:
    def __init__(
        self,
        stock_reports: pd.DataFrame,
        industry_reports: pd.DataFrame,
        stock_report_dir: Path,
        industry_report_dir: Path,
    ) -> None:
        self.stock_reports = stock_reports.copy()
        self.industry_reports = industry_reports.copy()
        self.stock_report_dir = stock_report_dir
        self.industry_report_dir = industry_report_dir
        self._stock_file_map = {path.name: path for path in stock_report_dir.glob("*.pdf")}
        self._industry_file_map = {path.name: path for path in industry_report_dir.glob("*.pdf")}

    def retrieve(
        self,
        question: str,
        companies: list[str] | None = None,
        focus_topics: list[str] | None = None,
        top_k: int = 5,
        source_scope: str = "hybrid",
    ) -> list[dict]:
        companies = companies or []
        focus_topics = focus_topics or []
        candidates = []
        if source_scope in {"hybrid", "stock"}:
            candidates.extend(self._score_rows(self.stock_reports, "stock", question, companies, focus_topics))
        if source_scope in {"hybrid", "industry"}:
            candidates.extend(self._score_rows(self.industry_reports, "industry", question, companies, focus_topics))
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        return [asdict(item) for item in ranked[:top_k] if item.score > 0]

    def _score_rows(
        self,
        df: pd.DataFrame,
        source_type: str,
        question: str,
        companies: list[str],
        focus_topics: list[str],
    ) -> list[RetrievedEvidence]:
        rows: list[RetrievedEvidence] = []
        if df.empty:
            return rows
        for row in df.to_dict(orient="records"):
            title = str(row.get("title", "") or "")
            normalized = normalize_report_metadata(row, source_type)
            score = 0.0
            for company in companies:
                if company and (company in title or company == str(row.get("stockName", ""))):
                    score += 3.0
            for topic in focus_topics:
                if topic and topic in title:
                    score += 2.0
            for token in str(question).split():
                if len(token) >= 2 and token in title:
                    score += 0.2
            if source_type == "industry" and any(token in question for token in ["行业", "板块", "医保目录", "集采"]):
                score += 1.0
            file_name = f"{title}.pdf"
            if source_type == "stock":
                file_path = self._stock_file_map.get(file_name)
                company_or_industry = str(row.get("stockName", "") or "")
                organization = str(row.get("orgSName", "") or row.get("orgName", "") or "")
            else:
                file_path = self._industry_file_map.get(file_name)
                company_or_industry = str(row.get("industryName", "") or "")
                organization = str(row.get("orgSName", "") or row.get("orgName", "") or "")
            snippet = "；".join(item for item in [title, company_or_industry, organization] if item)
            rows.append(
                RetrievedEvidence(
                    source_type=source_type,
                    title=title,
                    relative_path=str(file_path) if file_path else "",
                    publish_date=str(row.get("publishDate", "") or ""),
                    company_or_industry=company_or_industry,
                    organization=organization,
                    snippet=snippet,
                    score=score,
                    metadata_ref=str(normalized.get("metadata_ref", "") or ""),
                )
            )
        return rows


class VectorRetriever:
    def __init__(self, vector_store: Any, embedding_client: Any | None = None) -> None:
        self.vector_store = vector_store
        self.embedding_client = embedding_client
        self.last_error: str = ""

    def is_available(self) -> bool:
        return self.embedding_client is not None and self.vector_store.has_index()

    def retrieve(
        self,
        question: str,
        companies: list[str] | None = None,
        focus_topics: list[str] | None = None,
        top_k: int = 5,
        source_scope: str = "hybrid",
    ) -> list[dict[str, Any]]:
        if not self.embedding_client or not self.vector_store.has_index():
            return []
        try:
            query_embedding = self.embedding_client.embed([question])[0]
            self.last_error = ""
            return self.vector_store.search(
                query_embedding,
                top_k=top_k,
                source_scope=source_scope,
                companies=companies or [],
                focus_topics=focus_topics or [],
            )
        except Exception as exc:
            self.last_error = str(exc)
            return []


class HybridRetriever:
    def __init__(
        self,
        metadata_retriever: MetadataRetriever,
        vector_retriever: VectorRetriever | None = None,
    ) -> None:
        self.metadata_retriever = metadata_retriever
        self.vector_retriever = vector_retriever

    def retrieve(self, retrieval_plan: dict[str, object]) -> list[dict]:
        question = str(retrieval_plan.get("question", ""))
        companies = list(retrieval_plan.get("companies", []) or [])
        focus_topics = list(retrieval_plan.get("focus_topics", []) or [])
        top_k = int(retrieval_plan.get("top_k", 5) or 5)
        source_scope = str(retrieval_plan.get("source_scope", "hybrid") or "hybrid")
        retrieval_mode = str(retrieval_plan.get("retrieval_mode", "metadata") or "metadata")
        if retrieval_mode not in {"metadata", "hybrid", "vector"}:
            retrieval_mode = "metadata"

        metadata_hits = self.metadata_retriever.retrieve(
            question=question,
            companies=companies,
            focus_topics=focus_topics,
            top_k=top_k,
            source_scope=source_scope,
        )
        if retrieval_mode == "metadata" or self.vector_retriever is None:
            return metadata_hits

        vector_hits = self.vector_retriever.retrieve(
            question=question,
            companies=companies,
            focus_topics=focus_topics,
            top_k=top_k,
            source_scope=source_scope,
        )
        vector_error = getattr(self.vector_retriever, "last_error", "")
        if retrieval_mode == "vector":
            if vector_hits:
                return vector_hits
            return metadata_hits

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for item in metadata_hits:
            key = (str(item.get("title", "")), str(item.get("relative_path", "")))
            merged[key] = dict(item)
            merged[key]["score"] = float(item.get("score", 0.0))
            merged[key]["score_components"] = {"metadata": float(item.get("score", 0.0)), "vector": 0.0}
        for item in vector_hits:
            key = (str(item.get("title", "")), str(item.get("path", "")))
            if key not in merged:
                merged[key] = {
                    "source_type": item.get("source_type", ""),
                    "title": item.get("title", ""),
                    "relative_path": item.get("path", ""),
                    "publish_date": item.get("publish_date", ""),
                    "company_or_industry": item.get("company", "") or item.get("industry", ""),
                    "organization": item.get("organization", ""),
                    "metadata_ref": item.get("metadata_ref", ""),
                    "snippet": item.get("text", ""),
                    "score": 0.0,
                    "score_components": {"metadata": 0.0, "vector": 0.0},
                }
            merged[key]["score"] = float(merged[key].get("score", 0.0)) + float(item.get("score", 0.0))
            merged[key]["score_components"]["vector"] = float(item.get("score", 0.0))
            if vector_error:
                merged[key]["retrieval_warning"] = vector_error
        ranked = sorted(merged.values(), key=lambda row: float(row.get("score", 0.0)), reverse=True)
        results = ranked[:top_k]
        if vector_error and not vector_hits:
            for item in results:
                item["retrieval_warning"] = vector_error
        return results


__all__ = ["HybridRetriever", "MetadataRetriever", "VectorRetriever"]
