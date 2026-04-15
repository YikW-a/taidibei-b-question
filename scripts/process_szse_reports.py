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


DEFAULT_INPUT = Path("正式数据/附件2：财务报告/reports-深交所")
DEFAULT_OUTPUT = Path("正式数据/附件2：财务报告/reports-深交所_处理后")

PERIOD_MAP = {
    "第一季度": "一季度",
    "一季度": "一季度",
    "半年度": "半年度",
    "第三季度": "三季度",
    "三季度": "三季度",
    "年度": "年度",
}

PERIOD_PATTERN = re.compile(r"(第一季度|一季度|半年度|第三季度|三季度|年度)")
YEAR_PATTERN = re.compile(r"(20\d{2})年")


@dataclass(frozen=True)
class ReportCandidate:
    source_name: str
    source_path: str
    company_raw: str
    company_norm: str
    year: int
    period_raw: str
    period_norm: str
    report_type: str
    is_corrected: bool
    correction_tag: str
    has_duplicate_suffix: bool
    is_english_version: bool
    canonical_name: str


def normalize_company(name: str) -> str:
    return re.sub(r"\s+", "", name.strip())


def detect_report_type(rest: str) -> str:
    if "摘要" in rest:
        return "摘要"
    return "全文"


def detect_correction_tag(rest: str) -> str:
    if "更正后" in rest:
        return "更正后"
    if "更新后" in rest:
        return "更新后"
    return ""


def build_canonical_name(company: str, year: int, period: str, report_type: str) -> str:
    suffix = "摘要" if report_type == "摘要" else "全文"
    return f"{company}：{year}年{period}报告{suffix}.pdf"


def parse_filename(path: Path) -> ReportCandidate | None:
    if path.suffix.lower() != ".pdf":
        return None

    stem = path.stem
    if "：" not in stem:
        return None

    company_raw, rest = stem.split("：", 1)
    company_raw = company_raw.strip()
    rest = rest.strip()

    company_norm = normalize_company(company_raw)
    rest_no_spaces = re.sub(r"\s+", "", rest)
    if company_norm and rest_no_spaces.startswith(company_norm):
        rest = rest[len(company_norm) :].strip()

    year_match = YEAR_PATTERN.search(rest)
    period_match = PERIOD_PATTERN.search(rest)
    if not year_match or not period_match:
        return None

    year = int(year_match.group(1))
    period_raw = period_match.group(1)
    period_norm = PERIOD_MAP[period_raw]
    report_type = detect_report_type(rest)
    correction_tag = detect_correction_tag(rest)
    canonical_company = company_norm or company_raw.strip()

    return ReportCandidate(
        source_name=path.name,
        source_path=str(path),
        company_raw=company_raw,
        company_norm=canonical_company,
        year=year,
        period_raw=period_raw,
        period_norm=period_norm,
        report_type=report_type,
        is_corrected=bool(correction_tag),
        correction_tag=correction_tag,
        has_duplicate_suffix=stem.endswith("(1)"),
        is_english_version=("英文" in rest or "英文版" in rest),
        canonical_name=build_canonical_name(canonical_company, year, period_norm, report_type),
    )


def pick_best(candidates: list[ReportCandidate]) -> ReportCandidate:
    def rank(item: ReportCandidate) -> tuple[int, int, int, int, str]:
        return (
            1 if item.is_corrected else 0,
            1 if item.correction_tag == "更正后" else 0,
            0 if item.is_english_version else 1,
            0 if item.has_duplicate_suffix else 1,
            1 if "全文" in item.source_name else 0,
            item.source_name,
        )

    return max(candidates, key=rank)


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
        description="清洗深交所财报文件：保留摘要/全文，并对更正后版本优先合并。"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT, help="原始深交所财报目录")
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
        default="szse_reports_manifest",
        help="清单文件名前缀，默认 szse_reports_manifest",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir
    if not input_dir.exists():
        raise FileNotFoundError(f"input dir not found: {input_dir}")

    parsed: list[ReportCandidate] = []
    unparsable: list[str] = []
    for path in iter_pdf_files(input_dir):
        candidate = parse_filename(path)
        if candidate is None:
            unparsable.append(path.name)
            continue
        parsed.append(candidate)

    groups: dict[tuple[str, int, str, str], list[ReportCandidate]] = {}
    for item in parsed:
        key = (item.company_norm, item.year, item.period_norm, item.report_type)
        groups.setdefault(key, []).append(item)

    selected: list[ReportCandidate] = []
    manifest_rows: list[dict[str, object]] = []
    for key in sorted(groups):
        candidates = sorted(groups[key], key=lambda x: x.source_name)
        winner = pick_best(candidates)
        selected.append(winner)
        for item in candidates:
            manifest_rows.append(
                {
                    **asdict(item),
                    "group_key": "|".join(map(str, key)),
                    "group_size": len(candidates),
                    "selected": item.source_name == winner.source_name,
                    "selected_source": winner.source_name,
                    "selection_reason": (
                        "corrected_preferred"
                        if winner.is_corrected
                        else "single_or_best_available"
                    ),
                }
            )

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        for item in selected:
            dst = output_dir / item.canonical_name
            copy_file(Path(item.source_path), dst, args.mode)

    manifest_base = output_dir if not args.dry_run else input_dir
    manifest_base.mkdir(parents=True, exist_ok=True)
    csv_path = manifest_base / f"{args.manifest_prefix}.csv"
    json_path = manifest_base / f"{args.manifest_prefix}.json"

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
        "parsed_files": len(parsed),
        "unparsable_files": len(unparsable),
        "selected_files": len(selected),
        "groups_with_multiple_candidates": sum(1 for v in groups.values() if len(v) > 1),
        "unparsable_examples": unparsable[:20],
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary,
                "selected_files": [asdict(item) for item in selected],
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
