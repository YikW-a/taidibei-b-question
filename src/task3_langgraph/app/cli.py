from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..graph.runner import Task3LangGraphPrototype
from .common import resolve_config


def _print_kb_summary(summary: dict[str, object]) -> None:
    index_meta = dict(summary.get("index_meta", {}) or {})
    total_chunks = int(summary.get("chunk_count", 0) or 0)
    indexed_chunks = int(index_meta.get("chunk_count", 0) or 0)
    status = str(index_meta.get("index_status", "unknown") or "unknown")
    coverage = (indexed_chunks / total_chunks * 100.0) if total_chunks else 0.0
    print(
        "[kb-summary] "
        f"总 chunk={total_chunks} | "
        f"已建向量索引 chunk={indexed_chunks} | "
        f"覆盖率={coverage:.2f}% | "
        f"索引状态={status}",
        flush=True,
    )
    if total_chunks and indexed_chunks < total_chunks:
        print(
            "[kb-summary] 当前是局部向量知识库，适合小样本验证；如需更可靠的全量回答，建议先用 run_task3_index.py 完成全量建库。",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 3 LangGraph answering workflow")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--question-file", type=Path, default=None, help="问题文件路径，默认读取附件6")
    parser.add_argument("--output-dir", type=Path, default=None, help="回答输出目录，默认 outputs/task3_langgraph")
    parser.add_argument("--knowledge-base-dir", type=Path, default=None, help="知识库目录，默认与输出目录相同；测试集可指向已有 outputs/task3_langgraph")
    parser.add_argument("--question-id", type=str, default=None, help="单题调试，例如 B2001")
    parser.add_argument("--question-ids", type=str, default=None, help="逗号分隔题号列表")
    parser.add_argument("--sample-limit", type=int, default=None, help="随机抽样题数")
    parser.add_argument("--sample-seed", type=int, default=7, help="随机抽样种子")
    parser.add_argument("--llm-config", type=Path, default=None, help="LLM 配置文件，默认读取 configs/task3_llm.env")
    parser.add_argument("--embedding-batch-size", type=int, default=None, help="embedding 批大小")
    parser.add_argument("--embedding-batch-pause-seconds", type=float, default=None, help="embedding 批次间停顿秒数")
    parser.add_argument("--embedding-max-batches-per-run", type=int, default=None, help="单次运行最多构建多少批 embedding，便于断点续建")
    args = parser.parse_args()

    config = resolve_config(
        base_dir=args.base_dir,
        llm_config=args.llm_config,
        question_file=args.question_file,
        output_dir=args.output_dir,
        knowledge_base_dir=args.knowledge_base_dir,
        embedding_batch_size=args.embedding_batch_size,
        embedding_batch_pause_seconds=args.embedding_batch_pause_seconds,
        embedding_max_batches_per_run=args.embedding_max_batches_per_run,
        build_index_on_start=False,
    )

    runner = Task3LangGraphPrototype(config)
    kb_summary = runner.context.runtime.summarize_index_status() if runner.context is not None else {}
    _print_kb_summary(kb_summary)

    if args.question_id:
        result = runner.run_single(args.question_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    explicit_ids = None
    if args.question_ids:
        explicit_ids = [item.strip() for item in args.question_ids.split(",") if item.strip()]

    selected_ids = runner.select_question_ids(
        explicit_ids=explicit_ids,
        sample_limit=args.sample_limit,
        sample_seed=args.sample_seed,
    )
    if explicit_ids:
        print(f"question-id mode enabled: selected {len(selected_ids)} questions -> {', '.join(selected_ids)}")
    elif args.sample_limit:
        print(f"sample mode enabled: randomly selected {len(selected_ids)} questions with seed={args.sample_seed}")
    else:
        print(f"full mode enabled: selected all {len(selected_ids)} questions")

    states = runner.run_many(selected_ids, show_progress=True)
    summary = runner.export_batch_results(states)
    print("\nStatus summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
