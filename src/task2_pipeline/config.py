from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task2Config:
    base_dir: Path
    question_file: Path
    company_info_path: Path
    database_url: str
    output_dir: Path
    llm_mode: str = "template"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    sample_limit: int | None = None
    sample_seed: int = 42
    question_ids: tuple[str, ...] = ()

    @property
    def result_dir(self) -> Path:
        return self.output_dir / "result"

    @property
    def artifacts_dir(self) -> Path:
        return self.output_dir / "artifacts"

    @property
    def result_xlsx(self) -> Path:
        return self.output_dir / "result_2.xlsx"

    @property
    def query_cache_db(self) -> Path:
        return self.output_dir / "task2_query_cache.db"

    @staticmethod
    def default(base_dir: Path) -> "Task2Config":
        output_dir = base_dir / "outputs/task2"
        return Task2Config(
            base_dir=base_dir,
            question_file=base_dir / "正式数据/附件4：问题汇总.xlsx",
            company_info_path=base_dir / "正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx",
            database_url=f"sqlite:///{(base_dir / 'outputs/task1/task1_financials.db').as_posix()}",
            output_dir=output_dir,
        )
