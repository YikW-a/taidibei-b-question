from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineConfig:
    base_dir: Path
    input_manifest_sse: Path
    input_manifest_szse: Path
    company_info_path: Path
    output_dir: Path
    database_url: str
    sample_limit: int | None = None

    @property
    def logs_dir(self) -> Path:
        return self.output_dir / "logs"

    @property
    def artifacts_dir(self) -> Path:
        return self.output_dir / "artifacts"

    @property
    def evaluation_dir(self) -> Path:
        return self.output_dir / "evaluation"

    @classmethod
    def default(cls, base_dir: Path) -> "PipelineConfig":
        return cls(
            base_dir=base_dir,
            input_manifest_sse=base_dir / "正式数据/附件2：财务报告/reports-上交所_处理后/sse_reports_manifest.csv",
            input_manifest_szse=base_dir / "正式数据/附件2：财务报告/reports-深交所_处理后/szse_reports_manifest.csv",
            company_info_path=base_dir / "正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx",
            output_dir=base_dir / "outputs/task1",
            database_url=f"sqlite:///{(base_dir / 'outputs/task1/task1_financials.db').as_posix()}",
        )
