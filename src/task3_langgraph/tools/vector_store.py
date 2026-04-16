from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    faiss = None


class VectorStoreManager:
    """Resumable FAISS-backed vector store for Task 3.

    It stores:
    - chunk metadata
    - dense embeddings in a memmap file for resumable indexing
    - a persisted FAISS index file for retrieval
    - progress metadata for incremental embedding builds
    """

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.index_meta_path = self.store_dir / "index_meta.json"
        self.chunk_path = self.store_dir / "chunks.json"
        self.embedding_path = self.store_dir / "embeddings.dat"
        self.progress_path = self.store_dir / "index_progress.json"
        self.faiss_index_path = self.store_dir / "index.faiss"

    def save_index_meta(self, payload: dict[str, Any]) -> None:
        self.index_meta_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_index_meta(self) -> dict[str, Any]:
        if not self.index_meta_path.exists():
            return {}
        return json.loads(self.index_meta_path.read_text(encoding="utf-8"))

    def save_progress(self, payload: dict[str, Any]) -> None:
        self.progress_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_progress(self) -> dict[str, Any]:
        if not self.progress_path.exists():
            return {}
        return json.loads(self.progress_path.read_text(encoding="utf-8"))

    def reset_progress(self) -> None:
        if self.progress_path.exists():
            self.progress_path.unlink()

    def has_index(self) -> bool:
        meta = self.load_index_meta()
        if meta.get("index_status") != "ready":
            return False
        if self.chunk_path.exists() and self.faiss_index_path.exists() and meta.get("index_type") == "faiss_flat_ip":
            return True
        return (
            self.chunk_path.exists()
            and self.embedding_path.exists()
            and bool(meta.get("chunk_count"))
            and meta.get("index_status") == "ready"
        )

    def save_chunks(self, chunks: list[dict[str, Any]]) -> None:
        self.chunk_path.write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_chunks(self) -> list[dict[str, Any]]:
        if not self.chunk_path.exists():
            return []
        return json.loads(self.chunk_path.read_text(encoding="utf-8"))

    def load_embeddings(self) -> np.ndarray:
        meta = self.load_index_meta()
        chunk_count = int(meta.get("chunk_count", 0) or 0)
        embedding_dim = int(meta.get("embedding_dim", 0) or 0)
        if not self.embedding_path.exists() or not chunk_count or not embedding_dim:
            return np.empty((0, 0), dtype=np.float32)
        array = np.memmap(
            self.embedding_path,
            dtype=np.float32,
            mode="r",
            shape=(chunk_count, embedding_dim),
        )
        return np.asarray(array, dtype=np.float32)

    def build_index_resumable(
        self,
        chunks: list[dict[str, Any]],
        embedding_client: Any,
        *,
        embedding_model: str,
        batch_size: int = 16,
        pause_seconds: float = 1.0,
        max_batches: int | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not chunks:
            meta = {
                "index_type": self._preferred_index_type(),
                "embedding_model": embedding_model,
                "chunk_count": 0,
                "embedding_dim": 0,
                "index_status": "ready",
            }
            self.save_chunks([])
            self.save_index_meta(meta)
            self.reset_progress()
            return meta

        chunk_count = len(chunks)
        self.save_chunks(chunks)

        progress = self.load_progress()
        start_index = int(progress.get("next_index", 0) or 0)
        embedding_dim = int(progress.get("embedding_dim", 0) or 0)
        completed_batches = int(progress.get("completed_batches", 0) or 0)

        meta = self.load_index_meta()
        if (
            meta.get("embedding_model") != embedding_model
            or int(meta.get("chunk_count", 0) or 0) != chunk_count
        ):
            start_index = 0
            embedding_dim = 0
            completed_batches = 0
            if self.embedding_path.exists():
                self.embedding_path.unlink()
            if self.faiss_index_path.exists():
                self.faiss_index_path.unlink()

        batches_run = 0
        memmap = None
        try:
            for start in range(start_index, chunk_count, batch_size):
                if max_batches is not None and batches_run >= max_batches:
                    break
                batch_chunks = chunks[start : start + batch_size]
                batch_texts = [str(chunk.get("text", "") or "") for chunk in batch_chunks]
                batch_embeddings = embedding_client.embed(batch_texts)
                if not batch_embeddings:
                    raise RuntimeError("Embedding provider returned empty batch.")

                if embedding_dim == 0:
                    embedding_dim = len(batch_embeddings[0])
                    memmap = np.memmap(
                        self.embedding_path,
                        dtype=np.float32,
                        mode="w+",
                        shape=(chunk_count, embedding_dim),
                    )
                elif memmap is None:
                    memmap = np.memmap(
                        self.embedding_path,
                        dtype=np.float32,
                        mode="r+",
                        shape=(chunk_count, embedding_dim),
                    )

                batch_array = np.asarray(batch_embeddings, dtype=np.float32)
                end = start + len(batch_embeddings)
                memmap[start:end] = batch_array
                memmap.flush()

                completed_batches += 1
                batches_run += 1
                self.save_progress(
                    {
                        "embedding_model": embedding_model,
                        "chunk_count": chunk_count,
                        "embedding_dim": embedding_dim,
                        "next_index": end,
                        "completed_batches": completed_batches,
                        "last_batch_size": len(batch_embeddings),
                        "index_status": "building",
                    }
                )
                progress_payload = {
                    "embedding_model": embedding_model,
                    "chunk_count": chunk_count,
                    "embedding_dim": embedding_dim,
                    "next_index": end,
                    "completed_chunks": end,
                    "completed_batches": completed_batches,
                    "last_batch_size": len(batch_embeddings),
                    "remaining_chunks": max(0, chunk_count - end),
                    "index_status": "building",
                }
                self.save_index_meta(
                    {
                        "index_type": self._preferred_index_type(),
                        "embedding_model": embedding_model,
                        "chunk_count": chunk_count,
                        "embedding_dim": embedding_dim,
                        "index_status": "building",
                        "next_index": end,
                        "completed_batches": completed_batches,
                    }
                )
                if progress_callback is not None:
                    progress_callback(progress_payload)
                if end < chunk_count and pause_seconds > 0:
                    time.sleep(pause_seconds)
        finally:
            del memmap

        final_progress = self.load_progress()
        next_index = int(final_progress.get("next_index", start_index) or start_index)
        built_count = chunk_count if next_index >= chunk_count else next_index
        if built_count and embedding_dim:
            self._rebuild_search_index(chunk_count=built_count, embedding_dim=embedding_dim)

        if next_index >= chunk_count:
            meta = {
                "index_type": self._preferred_index_type(),
                "embedding_model": embedding_model,
                "chunk_count": chunk_count,
                "embedding_dim": embedding_dim,
                "index_status": "ready",
                "completed_batches": completed_batches,
            }
            self.save_index_meta(meta)
            self.reset_progress()
            return meta

        meta = {
            "index_type": self._preferred_index_type(),
            "embedding_model": embedding_model,
            "chunk_count": built_count,
            "embedding_dim": embedding_dim,
            "index_status": "partial",
            "next_index": next_index,
            "completed_batches": completed_batches,
        }
        self.save_index_meta(meta)
        return meta

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        source_scope: str = "hybrid",
        companies: list[str] | None = None,
        focus_topics: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        chunks = self.load_chunks()
        if not chunks:
            return []

        meta = self.load_index_meta()
        effective_chunk_count = int(meta.get("chunk_count", len(chunks)) or len(chunks))
        if effective_chunk_count <= 0:
            return []
        chunks = chunks[:effective_chunk_count]

        query = np.asarray(query_embedding, dtype=np.float32)
        if query.ndim != 1:
            query = query.reshape(-1)
        if not np.any(query):
            return []
        query = self._normalize_vector(query).astype(np.float32)

        if meta.get("index_type") == "faiss_flat_ip" and self.faiss_index_path.exists() and faiss is not None:
            scores = self._search_with_faiss(query, top_k=max(top_k * 10, top_k))
            return self._filter_and_rank_hits(
                chunks=chunks,
                raw_scores=scores,
                top_k=top_k,
                source_scope=source_scope,
                companies=companies or [],
                focus_topics=focus_topics or [],
            )

        embeddings = self.load_embeddings()
        if embeddings.size == 0:
            return []
        embeddings = embeddings[:effective_chunk_count]
        embeddings = self._normalize_matrix(embeddings)
        scores = embeddings @ query
        raw_scores = [(idx, float(score)) for idx, score in enumerate(scores)]
        return self._filter_and_rank_hits(
            chunks=chunks,
            raw_scores=raw_scores,
            top_k=top_k,
            source_scope=source_scope,
            companies=companies or [],
            focus_topics=focus_topics or [],
        )

    def _search_with_faiss(self, query: np.ndarray, *, top_k: int) -> list[tuple[int, float]]:
        index = faiss.read_index(str(self.faiss_index_path))
        scores, indices = index.search(query.reshape(1, -1), top_k)
        results: list[tuple[int, float]] = []
        for idx, score in zip(indices[0].tolist(), scores[0].tolist()):
            if idx < 0:
                continue
            results.append((int(idx), float(score)))
        return results

    def _filter_and_rank_hits(
        self,
        *,
        chunks: list[dict[str, Any]],
        raw_scores: list[tuple[int, float]],
        top_k: int,
        source_scope: str,
        companies: list[str],
        focus_topics: list[str],
    ) -> list[dict[str, Any]]:
        filtered: list[tuple[float, dict[str, Any]]] = []
        for index, base_score in raw_scores:
            if index < 0 or index >= len(chunks):
                continue
            chunk = chunks[index]
            if source_scope == "stock" and chunk.get("source_type") != "stock":
                continue
            if source_scope == "industry" and chunk.get("source_type") != "industry":
                continue
            bonus = 0.0
            chunk_company = str(chunk.get("company", "") or "")
            chunk_industry = str(chunk.get("industry", "") or "")
            chunk_text = str(chunk.get("text", "") or "")
            chunk_title = str(chunk.get("title", "") or "")
            for company in companies:
                if company and (
                    company in chunk_company
                    or company in chunk_industry
                    or company in chunk_text
                    or company in chunk_title
                ):
                    bonus += 0.05
            for topic in focus_topics:
                if topic and (topic in chunk_text or topic in chunk_title):
                    bonus += 0.03
            filtered.append((float(base_score) + bonus, chunk))

        ranked = sorted(filtered, key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        for score, chunk in ranked[:top_k]:
            item = dict(chunk)
            item["score"] = round(float(score), 6)
            results.append(item)
        return results

    def _rebuild_search_index(self, *, chunk_count: int, embedding_dim: int) -> None:
        if chunk_count <= 0 or embedding_dim <= 0:
            return
        embeddings = self._load_embedding_slice(chunk_count, embedding_dim)
        if embeddings.size == 0:
            return
        if faiss is None:
            return
        normalized = self._normalize_matrix(embeddings).astype(np.float32)
        index = faiss.IndexFlatIP(embedding_dim)
        index.add(normalized)
        faiss.write_index(index, str(self.faiss_index_path))

    def _load_embedding_slice(self, chunk_count: int, embedding_dim: int) -> np.ndarray:
        if not self.embedding_path.exists():
            return np.empty((0, 0), dtype=np.float32)
        array = np.memmap(
            self.embedding_path,
            dtype=np.float32,
            mode="r",
            shape=(chunk_count, embedding_dim),
        )
        return np.asarray(array, dtype=np.float32)

    @staticmethod
    def _preferred_index_type() -> str:
        return "faiss_flat_ip" if faiss is not None else "dense_exact"

    @staticmethod
    def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    @staticmethod
    def _normalize_vector(vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return vector / norm


__all__ = ["VectorStoreManager"]
