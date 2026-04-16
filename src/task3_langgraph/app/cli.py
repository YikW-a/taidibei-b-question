from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..graph.runner import Task3LangGraphPrototype
from .common import resolve_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 3 LangGraph answering workflow")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
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
        embedding_batch_size=args.embedding_batch_size,
        embedding_batch_pause_seconds=args.embedding_batch_pause_seconds,
        embedding_max_batches_per_run=args.embedding_max_batches_per_run,
        build_index_on_start=False,
    )

    runner = Task3LangGraphPrototype(config)

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
