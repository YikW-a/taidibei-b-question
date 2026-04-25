from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd


SSE_PATTERN = re.compile(
    r"^(?P<stock_code>\d{6})_(?P<report_date>\d{8})_(?P<random_id>[A-Z0-9]{4})\.pdf$",
    re.I,
)
SZSE_PERIOD_MAP = {
    "第一季度": ("一季度", "0331"),
    "一季度": ("一季度", "0331"),
    "半年度": ("半年度", "0630"),
    "第三季度": ("三季度", "0930"),
    "三季度": ("三季度", "0930"),
    "年度": ("年度", "1231"),
}
SZSE_PERIOD_PATTERN = re.compile(r"(第一季度|一季度|半年度|第三季度|三季度|年度)")
SZSE_YEAR_PATTERN = re.compile(r"(20\d{2})年")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def build_test_manifests(
    *,
    base_dir: Path,
    output_dir: Path,
    company_info_path: Path,
) -> tuple[Path, Path]:
    manifests_dir = output_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    sse_path = manifests_dir / "sse_reports_manifest.csv"
    szse_path = manifests_dir / "szse_reports_manifest.csv"

    sse_rows = _build_sse_manifest_rows(base_dir / "测试数据/附件2：财务报告/reports-上交所")
    szse_rows = _build_szse_manifest_rows(
        report_dir=base_dir / "测试数据/附件2：财务报告/reports-深交所",
        company_info_path=company_info_path,
    )

    _write_csv(sse_path, sse_rows)
    _write_csv(szse_path, szse_rows)
    return sse_path, szse_path


def _build_sse_manifest_rows(report_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(report_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        match = SSE_PATTERN.match(path.name)
        if not match:
            continue
        report_date = match.group("report_date")
        rows.append(
            {
                "source_name": path.name,
                "source_path": str(path),
                "stock_code": match.group("stock_code"),
                "report_date": report_date,
                "report_year": int(report_date[:4]),
            }
        )
    return rows


def _build_szse_manifest_rows(*, report_dir: Path, company_info_path: Path) -> list[dict[str, object]]:
    company_df = pd.read_excel(company_info_path, sheet_name="基本信息表")
    company_lookup = {
        str(row.get("A股简称", "")).strip().replace(" ", ""): str(row.get("股票代码", "")).split(".")[0].zfill(6)
        for row in company_df.to_dict(orient="records")
        if str(row.get("A股简称", "")).strip()
    }

    parsed_rows: list[dict[str, object]] = []
    for path in sorted(report_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        parsed = _parse_szse_filename(path, company_lookup)
        if parsed is not None:
            parsed_rows.append(parsed)

    groups: dict[tuple[str, int, str, str], list[dict[str, object]]] = {}
    for row in parsed_rows:
        key = (
            str(row.get("company_norm", "") or ""),
            int(row.get("year", 0) or 0),
            str(row.get("period_norm", "") or ""),
            str(row.get("report_type", "") or ""),
        )
        groups.setdefault(key, []).append(row)

    manifest_rows: list[dict[str, object]] = []
    for key in sorted(groups):
        candidates = sorted(groups[key], key=lambda item: str(item.get("source_name", "") or ""))
        winner = _pick_best_szse_candidate(candidates)
        winner_name = str(winner.get("source_name", "") or "")
        for item in candidates:
            manifest_rows.append(
                {
                    **item,
                    "group_key": "|".join(map(str, key)),
                    "group_size": len(candidates),
                    "selected": str(item.get("source_name", "") or "") == winner_name,
                    "selected_source": winner_name,
                    "selection_reason": (
                        "corrected_preferred"
                        if bool(winner.get("is_corrected", False))
                        else "single_or_best_available"
                    ),
                }
            )

    return manifest_rows


def _parse_szse_filename(path: Path, company_lookup: dict[str, str]) -> dict[str, object] | None:
    stem = path.stem
    if "：" not in stem:
        return None
    company_raw, rest = stem.split("：", 1)
    company_norm = re.sub(r"\s+", "", company_raw.strip())
    rest = rest.strip()
    rest_no_spaces = re.sub(r"\s+", "", rest)
    if company_norm and rest_no_spaces.startswith(company_norm):
        rest = rest[len(company_norm) :].strip()

    year_match = SZSE_YEAR_PATTERN.search(rest)
    period_match = SZSE_PERIOD_PATTERN.search(rest)
    if not year_match or not period_match:
        return None

    year = int(year_match.group(1))
    period_norm, period_suffix = SZSE_PERIOD_MAP[period_match.group(1)]
    report_type = "摘要" if "摘要" in rest else "全文"
    is_english_version = "英文" in rest or "英文版" in rest
    correction_tag = "更正后" if "更正后" in rest else ("更新后" if "更新后" in rest else "")
    is_corrected = bool(correction_tag)
    has_duplicate_suffix = stem.endswith("(1)")

    return {
        "source_name": path.name,
        "source_path": str(path),
        "company_norm": company_norm,
        "stock_abbr": company_norm,
        "stock_code": company_lookup.get(company_norm),
        "report_date": f"{year}{period_suffix}",
        "year": year,
        "period_norm": period_norm,
        "report_type": report_type,
        "is_corrected": is_corrected,
        "correction_tag": correction_tag,
        "has_duplicate_suffix": has_duplicate_suffix,
        "is_english_version": is_english_version,
    }


def _pick_best_szse_candidate(candidates: list[dict[str, object]]) -> dict[str, object]:
    def rank(item: dict[str, object]) -> tuple[int, int, int, int, int, str]:
        source_name = str(item.get("source_name", "") or "")
        return (
            1 if bool(item.get("is_corrected", False)) else 0,
            1 if str(item.get("correction_tag", "") or "") == "更正后" else 0,
            0 if bool(item.get("is_english_version", False)) else 1,
            0 if bool(item.get("has_duplicate_suffix", False)) else 1,
            1 if "全文" in source_name else 0,
            source_name,
        )

    return max(candidates, key=rank)
