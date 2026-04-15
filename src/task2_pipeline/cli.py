from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import Task2Config
from .pipeline import Task2Pipeline


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
    parser = argparse.ArgumentParser(description="Task 2: 财务问数、图表与结果导出")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录")
    parser.add_argument("--database-url", type=str, default=None, help="数据库连接串")
    parser.add_argument("--mode", type=str, choices=["template", "llm"], default=None, help="任务二运行模式")
    parser.add_argument("--llm-config", type=Path, default=None, help="LLM 配置文件，默认读取 configs/task2_llm.env")
    parser.add_argument("--llm-base-url", type=str, default=None, help="OpenAI 兼容接口 base url，例如 https://api.openai.com/v1")
    parser.add_argument("--llm-api-key", type=str, default=None, help="模型 API Key")
    parser.add_argument("--llm-model", type=str, default=None, help="模型名称")
    parser.add_argument("--sample-limit", type=int, default=None, help="随机抽样问题数量，例如 10")
    parser.add_argument("--sample-seed", type=int, default=42, help="随机抽样种子")
    parser.add_argument("--question-ids", type=str, default=None, help="按题号定向运行，逗号分隔，例如 B1001,B1046")
    args = parser.parse_args()

    config = Task2Config.default(args.base_dir)
    llm_config_path = args.llm_config or (args.base_dir / "configs/task2_llm.env")
    file_values = _load_env_file(llm_config_path)
    llm_mode = args.mode or ("llm" if (args.llm_base_url or file_values.get("TASK2_LLM_BASE_URL") or os.getenv("TASK2_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")) else "template")
    llm_base_url = args.llm_base_url or file_values.get("TASK2_LLM_BASE_URL") or os.getenv("TASK2_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    llm_api_key = args.llm_api_key or file_values.get("TASK2_LLM_API_KEY") or os.getenv("TASK2_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_model = args.llm_model or file_values.get("TASK2_LLM_MODEL") or os.getenv("TASK2_LLM_MODEL") or os.getenv("OPENAI_MODEL")
    question_ids = tuple(item.strip() for item in (args.question_ids or "").split(",") if item.strip())
    if args.output_dir is not None:
        config = Task2Config(
            base_dir=config.base_dir,
            question_file=config.question_file,
            company_info_path=config.company_info_path,
            database_url=args.database_url or config.database_url,
            output_dir=args.output_dir,
            llm_mode=llm_mode,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            sample_limit=args.sample_limit,
            sample_seed=args.sample_seed,
            question_ids=question_ids,
        )
    elif args.database_url is not None or llm_mode != config.llm_mode:
        config = Task2Config(
            base_dir=config.base_dir,
            question_file=config.question_file,
            company_info_path=config.company_info_path,
            database_url=args.database_url or config.database_url,
            output_dir=config.output_dir,
            llm_mode=llm_mode,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            sample_limit=args.sample_limit,
            sample_seed=args.sample_seed,
            question_ids=question_ids,
        )
    elif args.sample_limit is not None or args.sample_seed != 42 or question_ids:
        config = Task2Config(
            base_dir=config.base_dir,
            question_file=config.question_file,
            company_info_path=config.company_info_path,
            database_url=config.database_url,
            output_dir=config.output_dir,
            llm_mode=llm_mode,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            sample_limit=args.sample_limit,
            sample_seed=args.sample_seed,
            question_ids=question_ids,
        )

    df = Task2Pipeline(config).run()
    print(df[["question_id", "intent_type", "status"]].head(10).to_string(index=False))
    print()
    print("Status summary:")
    print(df["status"].value_counts().to_string())
    error_df = df[df["status"] == "error"]
    if not error_df.empty:
        print()
        print("First error samples:")
        preview_cols = ["question_id", "status", "note"]
        print(error_df[preview_cols].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
