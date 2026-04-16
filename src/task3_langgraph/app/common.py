from __future__ import annotations

import os
from pathlib import Path

from ..config.settings import Task3LangGraphConfig


def load_env_file(path: Path) -> dict[str, str]:
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


def resolve_config(
    *,
    base_dir: Path,
    llm_config: Path | None = None,
    index_limit: int | None = None,
    embedding_batch_size: int | None = None,
    embedding_batch_pause_seconds: float | None = None,
    embedding_max_batches_per_run: int | None = None,
    build_index_on_start: bool = True,
) -> Task3LangGraphConfig:
    base_config = Task3LangGraphConfig.default(base_dir)
    llm_config_path = llm_config or (base_dir / "configs/task3_llm.env")
    fallback_task2_config_path = base_dir / "configs/task2_llm.env"
    if not llm_config_path.exists():
        llm_config_path = fallback_task2_config_path
    file_values = load_env_file(llm_config_path)
    fallback_file_values: dict[str, str] = {}
    if llm_config_path != fallback_task2_config_path and fallback_task2_config_path.exists():
        fallback_file_values = load_env_file(fallback_task2_config_path)
    env = os.environ
    return Task3LangGraphConfig(
        base_dir=base_config.base_dir,
        question_file=base_config.question_file,
        company_info_path=base_config.company_info_path,
        stock_report_info_path=base_config.stock_report_info_path,
        industry_report_info_path=base_config.industry_report_info_path,
        report_field_desc_path=base_config.report_field_desc_path,
        stock_report_dir=base_config.stock_report_dir,
        industry_report_dir=base_config.industry_report_dir,
        database_url=base_config.database_url,
        output_dir=base_config.output_dir,
        llm_mode="llm",
        llm_base_url=env.get("TASK3_LLM_BASE_URL")
        or file_values.get("TASK3_LLM_BASE_URL")
        or env.get("TASK2_LLM_BASE_URL")
        or file_values.get("TASK2_LLM_BASE_URL")
        or fallback_file_values.get("TASK2_LLM_BASE_URL"),
        llm_api_key=env.get("TASK3_LLM_API_KEY")
        or file_values.get("TASK3_LLM_API_KEY")
        or env.get("TASK2_LLM_API_KEY")
        or file_values.get("TASK2_LLM_API_KEY")
        or fallback_file_values.get("TASK2_LLM_API_KEY"),
        llm_model=env.get("TASK3_LLM_MODEL")
        or file_values.get("TASK3_LLM_MODEL")
        or env.get("TASK2_LLM_MODEL")
        or file_values.get("TASK2_LLM_MODEL")
        or fallback_file_values.get("TASK2_LLM_MODEL"),
        embedding_base_url=env.get("TASK3_EMBEDDING_BASE_URL")
        or file_values.get("TASK3_EMBEDDING_BASE_URL")
        or env.get("TASK2_LLM_BASE_URL")
        or file_values.get("TASK2_LLM_BASE_URL")
        or fallback_file_values.get("TASK2_LLM_BASE_URL"),
        embedding_api_key=env.get("TASK3_EMBEDDING_API_KEY")
        or file_values.get("TASK3_EMBEDDING_API_KEY")
        or env.get("TASK2_LLM_API_KEY")
        or file_values.get("TASK2_LLM_API_KEY")
        or fallback_file_values.get("TASK2_LLM_API_KEY"),
        embedding_model=env.get("TASK3_EMBEDDING_MODEL") or file_values.get("TASK3_EMBEDDING_MODEL"),
        index_limit=index_limit,
        embedding_batch_size=embedding_batch_size or base_config.embedding_batch_size,
        embedding_batch_pause_seconds=embedding_batch_pause_seconds
        if embedding_batch_pause_seconds is not None
        else base_config.embedding_batch_pause_seconds,
        embedding_max_batches_per_run=embedding_max_batches_per_run,
        build_index_on_start=build_index_on_start,
    )


__all__ = ["load_env_file", "resolve_config"]
