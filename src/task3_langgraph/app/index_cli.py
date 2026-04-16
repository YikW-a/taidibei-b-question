from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from ..nodes import Task3NodeContext
from .common import resolve_config

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None


def _print_index_progress(payload: dict[str, object]) -> None:
    completed = int(payload.get("completed_chunks", 0) or 0)
    total = int(payload.get("chunk_count", 0) or 0)
    next_index = int(payload.get("next_index", 0) or 0)
    completed_batches = int(payload.get("completed_batches", 0) or 0)
    remaining = int(payload.get("remaining_chunks", max(0, total - completed)) or 0)
    print(
        f"[index] batch={completed_batches} completed={completed}/{total} "
        f"remaining={remaining} next_resume={next_index}",
        flush=True,
    )


def _build_index_progress_handler(total_chunks: int, initial_completed: int = 0):
    state: dict[str, object] = {"progress_bar": None}
    last_completed = max(0, initial_completed)
    if tqdm is not None and total_chunks > 0:
        progress_bar = tqdm(total=total_chunks, desc="Task3 Index", unit="chunk")
        if last_completed:
            progress_bar.update(last_completed)
            progress_bar.set_postfix_str(f"resume_from={last_completed}")
        state["progress_bar"] = progress_bar

    def _handler(payload: dict[str, object]) -> None:
        nonlocal last_completed
        completed = int(payload.get("completed_chunks", 0) or 0)
        payload_total = int(payload.get("chunk_count", total_chunks) or total_chunks)
        remaining = int(payload.get("remaining_chunks", max(0, payload_total - completed)) or 0)
        next_index = int(payload.get("next_index", completed) or completed)
        completed_batches = int(payload.get("completed_batches", 0) or 0)
        delta = max(0, completed - last_completed)
        progress_bar = state.get("progress_bar")
        if progress_bar is None and tqdm is not None and payload_total > 0:
            progress_bar = tqdm(total=payload_total, desc="Task3 Index", unit="chunk")
            if last_completed:
                progress_bar.update(last_completed)  # type: ignore[union-attr]
            state["progress_bar"] = progress_bar
        if progress_bar is not None:
            if delta:
                progress_bar.update(delta)  # type: ignore[union-attr]
            progress_bar.set_postfix_str(  # type: ignore[union-attr]
                f"batch={completed_batches} remaining={remaining} next_resume={next_index}"
            )
        else:
            _print_index_progress(payload)
        last_completed = max(last_completed, completed)

    return state, _handler


def _ensure_progress_bar(state: dict[str, object], *, total_chunks: int, initial_completed: int = 0):
    progress_bar = state.get("progress_bar")
    if progress_bar is not None or tqdm is None or total_chunks <= 0:
        return progress_bar
    progress_bar = tqdm(total=total_chunks, desc="Task3 Index", unit="chunk")
    if initial_completed:
        progress_bar.update(initial_completed)
        progress_bar.set_postfix_str(f"resume_from={initial_completed}")
    state["progress_bar"] = progress_bar
    return progress_bar


def _load_existing_chunk_count(base_dir: Path) -> int:
    manifest_path = base_dir / "outputs/task3_langgraph/artifacts/chunks/report_chunks.json"
    if not manifest_path.exists():
        return 0
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return len(payload)
    except Exception:
        return 0
    return 0


def _load_existing_completed(base_dir: Path) -> int:
    progress_path = base_dir / "outputs/task3_langgraph/artifacts/vector_store/index_progress.json"
    meta_path = base_dir / "outputs/task3_langgraph/artifacts/vector_store/index_meta.json"
    for path in [progress_path, meta_path]:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            next_index = int(payload.get("next_index", 0) or 0)
            if next_index > 0:
                return next_index
            if str(payload.get("index_status", "")) == "ready":
                return int(payload.get("chunk_count", 0) or 0)
        except Exception:
            continue
    return 0


def _print_chunk_quality_samples(samples: list[dict[str, object]]) -> None:
    if not samples:
        return
    print("[chunk-samples] 以下为自动抽样的 chunk 质量样本：", flush=True)
    for idx, sample in enumerate(samples, start=1):
        source_type = str(sample.get("source_type", "") or "")
        chunk_type = str(sample.get("chunk_type", "") or "")
        page_start = sample.get("page_start", 0)
        page_end = sample.get("page_end", 0)
        title = str(sample.get("title", "") or "")
        preview = str(sample.get("text_preview", "") or "").replace("\n", " ")
        print(
            f"  [{idx}] {source_type}/{chunk_type} p{page_start}-{page_end} | {title} | {preview}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 3 knowledge-base indexing workflow")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--llm-config", type=Path, default=None, help="配置文件，默认读取 configs/task3_llm.env")
    parser.add_argument("--index-limit", type=int, default=None, help="仅构建前 N 个 chunk 的向量索引")
    parser.add_argument("--embedding-batch-size", type=int, default=None, help="embedding 批大小")
    parser.add_argument("--embedding-batch-pause-seconds", type=float, default=None, help="embedding 批次间停顿秒数")
    parser.add_argument("--embedding-max-batches-per-run", type=int, default=None, help="单次运行最多构建多少批 embedding，便于断点续建")
    parser.add_argument("--retrieval-smoke-question", type=str, default=None, help="检索冒烟测试问题")
    parser.add_argument("--retrieval-mode", type=str, default=None, help="retrieval 模式：metadata/vector/hybrid")
    args = parser.parse_args()

    config = resolve_config(
        base_dir=args.base_dir,
        llm_config=args.llm_config,
        index_limit=args.index_limit,
        embedding_batch_size=args.embedding_batch_size,
        embedding_batch_pause_seconds=args.embedding_batch_pause_seconds,
        embedding_max_batches_per_run=args.embedding_max_batches_per_run,
    )
    if args.retrieval_smoke_question:
        config = replace(config, build_index_on_start=False)
    existing_chunk_count = _load_existing_chunk_count(args.base_dir)
    existing_completed = _load_existing_completed(args.base_dir)
    progress_state, progress_handler = _build_index_progress_handler(existing_chunk_count, existing_completed)
    ctx = Task3NodeContext(config, index_progress_callback=progress_handler)

    if args.retrieval_smoke_question:
        payload = ctx.runtime.retrieval_smoke_test(
            args.retrieval_smoke_question,
            retrieval_mode=args.retrieval_mode,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return

    summary = ctx.runtime.summarize_index_status()
    summary_chunk_count = int(summary.get("chunk_count", 0) or 0)
    summary_completed = int(summary.get("completed_chunk_count", 0) or 0)
    progress_bar = _ensure_progress_bar(
        progress_state,
        total_chunks=summary_chunk_count,
        initial_completed=summary_completed,
    )
    if progress_bar is not None:
        progress_bar.total = summary_chunk_count
        if progress_bar.n < summary_completed:
            progress_bar.update(summary_completed - progress_bar.n)
        progress_bar.refresh()
    print(
        "[index-summary] "
        f"个股研报={summary['stock_report_count']} | "
        f"行业研报={summary['industry_report_count']} | "
        f"个股 chunk={summary['stock_chunk_count']} | "
        f"行业 chunk={summary['industry_chunk_count']} | "
        f"正文抽取成功研报={summary['pdf_extracted_report_count']} | "
        f"metadata fallback 研报={summary['metadata_fallback_report_count']} | "
        f"总 chunk={summary['chunk_count']} | "
        f"已完成={summary['completed_chunk_count']} | "
        f"剩余={summary['remaining_chunk_count']} | "
        f"当前索引状态={summary['index_meta'].get('index_status', 'unknown')} | "
        f"下次续跑起点={summary['next_resume_index']}",
        flush=True,
    )
    _print_chunk_quality_samples(list(summary.get("chunk_quality_samples", []) or []))
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )
    if progress_bar is not None:
        progress_bar.close()


__all__ = ["main"]
