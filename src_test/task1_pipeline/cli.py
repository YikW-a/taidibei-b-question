from __future__ import annotations

import argparse
from pathlib import Path

from .config import PipelineConfig
from .pipeline import Task1Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 1: test dataset pipeline")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录，默认 outputs_test/task1")
    parser.add_argument("--database-url", type=str, default=None, help="数据库连接串")
    parser.add_argument("--sample-limit", type=int, default=None, help="仅处理前 N 份文件")
    args = parser.parse_args()

    config = PipelineConfig.default(args.base_dir)
    output_dir = args.output_dir or config.output_dir
    config = PipelineConfig(
        base_dir=config.base_dir,
        input_manifest_sse=output_dir / "manifests/sse_reports_manifest.csv",
        input_manifest_szse=output_dir / "manifests/szse_reports_manifest.csv",
        company_info_path=config.company_info_path,
        output_dir=output_dir,
        database_url=args.database_url or f"sqlite:///{(output_dir / 'task1_financials.db').as_posix()}",
        sample_limit=args.sample_limit,
    )

    summary = Task1Pipeline(config).run()
    print(summary)


if __name__ == "__main__":
    main()
