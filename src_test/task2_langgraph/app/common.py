from __future__ import annotations

from pathlib import Path

from ..config.settings import Task2LangGraphConfig


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
    question_file: Path | None = None,
    output_dir: Path | None = None,
    company_info_path: Path | None = None,
    database_url: str | None = None,
) -> Task2LangGraphConfig:
    base_config = Task2LangGraphConfig.default(base_dir)
    llm_config_path = llm_config or (base_dir / "configs/task2_llm.env")
    file_values = load_env_file(llm_config_path)
    return Task2LangGraphConfig(
        base_dir=base_config.base_dir,
        question_file=question_file or base_config.question_file,
        company_info_path=company_info_path or base_config.company_info_path,
        database_url=database_url or base_config.database_url,
        output_dir=output_dir or base_config.output_dir,
        llm_mode="llm",
        llm_base_url=file_values.get("TASK2_LLM_BASE_URL"),
        llm_api_key=file_values.get("TASK2_LLM_API_KEY"),
        llm_model=file_values.get("TASK2_LLM_MODEL"),
    )


__all__ = ["load_env_file", "resolve_config"]
