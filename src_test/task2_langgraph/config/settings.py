from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task2LangGraphConfig:
    base_dir: Path
    question_file: Path
    company_info_path: Path
    database_url: str
    output_dir: Path
    llm_mode: str = "llm"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    @property
    def result_dir(self) -> Path:
        return self.output_dir / "result"

    @property
    def artifacts_dir(self) -> Path:
        return self.output_dir / "artifacts"

    @property
    def chart_spec_dir(self) -> Path:
        return self.artifacts_dir / "chart_specs"

    @property
    def query_cache_db(self) -> Path:
        return self.output_dir / "task2_langgraph_query_cache.db"

    @staticmethod
    def default(base_dir: Path) -> "Task2LangGraphConfig":
        return Task2LangGraphConfig(
            base_dir=base_dir,
            question_file=base_dir / "测试数据/附件4：问题汇总.xlsx",
            company_info_path=base_dir / "测试数据/附件1：医药上市公司基本信息（截至到2026年1月13日）.xlsx",
            database_url=f"sqlite:///{(base_dir / 'outputs_test/task1/task1_financials.db').as_posix()}",
            output_dir=base_dir / "outputs_test/task2_langgraph",
        )
