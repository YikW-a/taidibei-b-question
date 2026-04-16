from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..nodes import Task3NodeContext
from .common import resolve_config


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
    ctx = Task3NodeContext(config, index_progress_callback=_print_index_progress)

    if args.retrieval_smoke_question:
        payload = ctx.runtime.retrieval_smoke_test(
            args.retrieval_smoke_question,
            retrieval_mode=args.retrieval_mode,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return

    summary = ctx.runtime.summarize_index_status()
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
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


__all__ = ["main"]
