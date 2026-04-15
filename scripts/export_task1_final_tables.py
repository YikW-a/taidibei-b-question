from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.task1_pipeline.db import TABLE_SCHEMAS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Task 1: 重新导出四张最终业务表")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="数据库连接串。默认读取 outputs/task1/task1_financials.db",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/task1/final_tables"),
        help="最终业务表输出目录",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    default_database_url = f"sqlite:///{(Path.cwd() / 'outputs/task1/task1_financials.db').as_posix()}"
    engine = create_engine(args.database_url or default_database_url)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for table_name, schema in TABLE_SCHEMAS.items():
        schema_columns = [column_name for column_name, _ in schema]
        dataframe = pd.read_sql_table(table_name, engine)
        for column_name in schema_columns:
            if column_name not in dataframe.columns:
                dataframe[column_name] = pd.NA
        dataframe = dataframe[schema_columns]
        output_path = args.output_dir / f"{table_name}.csv"
        dataframe.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"exported {table_name}: {output_path}")


if __name__ == "__main__":
    main()
