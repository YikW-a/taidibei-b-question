from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..graph.runner import Task2LangGraphPrototype

from .common import resolve_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 2 LangGraph prototype for test dataset")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--question-file", type=Path, default=None, help="问题文件路径，默认读取测试数据附件4")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录，默认 outputs_test/task2_langgraph")
    parser.add_argument("--question-id", type=str, default=None, help="单题原型调试，例如 B1006")
    parser.add_argument("--question-ids", type=str, default=None, help="逗号分隔题号列表，例如 B1001,B1006")
    parser.add_argument("--sample-limit", type=int, default=None, help="随机抽样题数")
    parser.add_argument("--sample-seed", type=int, default=7, help="随机抽样种子")
    parser.add_argument("--llm-config", type=Path, default=None, help="LLM 配置文件，默认读取 configs/task2_llm.env")
    args = parser.parse_args()

    config = resolve_config(
        base_dir=args.base_dir,
        llm_config=args.llm_config,
        question_file=args.question_file,
        output_dir=args.output_dir,
    )
    runner = Task2LangGraphPrototype(config)

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
