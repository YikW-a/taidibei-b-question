from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task3LangGraphConfig:
    base_dir: Path
    question_file: Path
    company_info_path: Path
    stock_report_info_path: Path
    industry_report_info_path: Path
    report_field_desc_path: Path
    stock_report_dir: Path
    industry_report_dir: Path
    database_url: str
    output_dir: Path
    llm_mode: str = "llm"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    chunk_size_chars: int = 900
    chunk_overlap_chars: int = 150
    max_pages_per_report: int = 100
    embedding_batch_size: int = 16
    index_limit: int | None = None
    embedding_batch_pause_seconds: float = 1.0
    embedding_max_batches_per_run: int | None = None
    build_index_on_start: bool = True

    @property
    def result_dir(self) -> Path:
        return self.output_dir / "result"

    @property
    def artifacts_dir(self) -> Path:
        return self.output_dir / "artifacts"

    @property
    def debug_dir(self) -> Path:
        return self.artifacts_dir / "debug"

    @property
    def retrieval_dir(self) -> Path:
        return self.artifacts_dir / "retrieval"

    @property
    def vector_store_dir(self) -> Path:
        return self.artifacts_dir / "vector_store"

    @property
    def chunk_dir(self) -> Path:
        return self.artifacts_dir / "chunks"

    @property
    def query_cache_db(self) -> Path:
        return self.output_dir / "task3_langgraph_query_cache.db"

    @staticmethod
    def default(base_dir: Path) -> "Task3LangGraphConfig":
        return Task3LangGraphConfig(
            base_dir=base_dir,
            question_file=base_dir / "正式数据/附件6：问题汇总.xlsx",
            company_info_path=base_dir / "正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx",
            stock_report_info_path=base_dir / "正式数据/附件5：研报数据/个股_研报信息.xlsx",
            industry_report_info_path=base_dir / "正式数据/附件5：研报数据/行业_研报信息.xlsx",
            report_field_desc_path=base_dir / "正式数据/附件5：研报数据/字段说明.xlsx",
            stock_report_dir=base_dir / "正式数据/附件5：研报数据/个股研报",
            industry_report_dir=base_dir / "正式数据/附件5：研报数据/行业研报",
            database_url=f"sqlite:///{(base_dir / 'outputs/task1/task1_financials.db').as_posix()}",
            output_dir=base_dir / "outputs/task3_langgraph",
        )
