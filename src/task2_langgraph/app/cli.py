from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config.settings import Task2LangGraphConfig
from ..graph.runner import Task2LangGraphPrototype


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 2 LangGraph prototype")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--question-id", type=str, default=None, help="单题原型调试，例如 B1006")
    parser.add_argument("--question-ids", type=str, default=None, help="逗号分隔题号列表，例如 B1001,B1006")
    parser.add_argument("--sample-limit", type=int, default=None, help="随机抽样题数")
    parser.add_argument("--sample-seed", type=int, default=7, help="随机抽样种子")
    parser.add_argument("--llm-config", type=Path, default=None, help="LLM 配置文件，默认读取 configs/task2_llm.env")
    args = parser.parse_args()

    base_config = Task2LangGraphConfig.default(args.base_dir)
    llm_config_path = args.llm_config or (args.base_dir / "configs/task2_llm.env")
    file_values = _load_env_file(llm_config_path)
    config = Task2LangGraphConfig(
        base_dir=base_config.base_dir,
        question_file=base_config.question_file,
        company_info_path=base_config.company_info_path,
        database_url=base_config.database_url,
        output_dir=base_config.output_dir,
        llm_mode="llm",
        llm_base_url=file_values.get("TASK2_LLM_BASE_URL"),
        llm_api_key=file_values.get("TASK2_LLM_API_KEY"),
        llm_model=file_values.get("TASK2_LLM_MODEL"),
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
