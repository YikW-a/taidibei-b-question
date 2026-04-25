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

    @property
    def manifests_dir(self) -> Path:
        return self.output_dir / "manifests"

    @classmethod
    def default(cls, base_dir: Path) -> "PipelineConfig":
        output_dir = base_dir / "outputs_test/task1"
        return cls(
            base_dir=base_dir,
            input_manifest_sse=output_dir / "manifests/sse_reports_manifest.csv",
            input_manifest_szse=output_dir / "manifests/szse_reports_manifest.csv",
            company_info_path=base_dir / "测试数据/附件1：医药上市公司基本信息（截至到2026年1月13日）.xlsx",
            output_dir=output_dir,
            database_url=f"sqlite:///{(output_dir / 'task1_financials.db').as_posix()}",
        )
