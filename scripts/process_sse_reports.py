#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT = Path("正式数据/附件2：财务报告/reports-上交所")
DEFAULT_OUTPUT = Path("正式数据/附件2：财务报告/reports-上交所_处理后")
FILENAME_PATTERN = re.compile(r"^(?P<stock_code>\d{6})_(?P<report_date>\d{8})_(?P<random_id>[A-Z0-9]{4})\.pdf$", re.I)


@dataclass(frozen=True)
class ReportRecord:
    source_name: str
    source_path: str
    stock_code: str
    report_date: str
    random_id: str
    report_year: int


def parse_filename(path: Path) -> ReportRecord | None:
    if path.suffix.lower() != ".pdf":
        return None

    match = FILENAME_PATTERN.match(path.name)
    if not match:
        return None

    stock_code = match.group("stock_code")
    report_date = match.group("report_date")
    random_id = match.group("random_id").upper()
    report_year = int(report_date[:4])

    return ReportRecord(
        source_name=path.name,
        source_path=str(path),
        stock_code=stock_code,
        report_date=report_date,
        random_id=random_id,
        report_year=report_year,
    )


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, dst: Path, mode: str) -> None:
    ensure_parent(dst)
    if dst.exists():
        dst.unlink()

    if mode == "copy":
        shutil.copy2(src, dst)
    elif mode == "hardlink":
        dst.hardlink_to(src)
    elif mode == "symlink":
        dst.symlink_to(src.resolve())
    else:
        raise ValueError(f"unsupported mode: {mode}")


def iter_pdf_files(input_dir: Path) -> Iterable[Path]:
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() == ".pdf":
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="整理上交所财报文件：复制原文件到处理后目录，并生成 csv/json 清单。"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT, help="原始上交所财报目录")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="处理后的输出目录")
    parser.add_argument(
        "--mode",
        choices=["copy", "hardlink", "symlink"],
        default="copy",
        help="输出文件写入方式，默认 copy",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计和生成清单，不输出文件")
    parser.add_argument(
        "--manifest-prefix",
        default="sse_reports_manifest",
        help="清单文件名前缀，默认 sse_reports_manifest",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir
    if not input_dir.exists():
        raise FileNotFoundError(f"input dir not found: {input_dir}")

    records: list[ReportRecord] = []
    unparsable: list[str] = []
    for path in iter_pdf_files(input_dir):
        record = parse_filename(path)
        if record is None:
            unparsable.append(path.name)
            continue
        records.append(record)

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        for item in records:
            dst = output_dir / item.source_name
            copy_file(Path(item.source_path), dst, args.mode)

    manifest_base = output_dir if not args.dry_run else input_dir
    manifest_base.mkdir(parents=True, exist_ok=True)
    csv_path = manifest_base / f"{args.manifest_prefix}.csv"
    json_path = manifest_base / f"{args.manifest_prefix}.json"

    manifest_rows = [asdict(item) for item in records]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()) if manifest_rows else [])
        if manifest_rows:
            writer.writeheader()
            writer.writerows(manifest_rows)

    summary = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "mode": args.mode,
        "dry_run": args.dry_run,
        "parsed_files": len(records),
        "unparsable_files": len(unparsable),
        "unparsable_examples": unparsable[:20],
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary,
                "records": manifest_rows,
                "unparsable_files": unparsable,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"manifest csv: {csv_path}")
    print(f"manifest json: {json_path}")
    if not args.dry_run:
        print(f"written files: {output_dir}")


if __name__ == "__main__":
    main()
