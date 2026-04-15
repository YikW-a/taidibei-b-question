from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

import fitz
import pandas as pd

from .metadata import enrich_report_with_cover_text
from .mappings import FIELD_ALIASES, TABLE_KEYWORDS
from .models import ExtractedTable, ReportFile
from .normalizers import clean_label, detect_unit, parse_numeric

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    import camelot
except Exception:  # pragma: no cover
    camelot = None


@dataclass
class PDFExtractor:
    max_tables_per_page: int = 5

    def extract(self, report_file: ReportFile) -> list[ExtractedTable]:
        doc = fitz.open(report_file.source_path)
        cover_text = ""
        for idx in range(min(3, len(doc))):
            cover_text += (doc[idx].get_text() or "") + "\n"
        enrich_report_with_cover_text(report_file, cover_text)
        extracted: list[ExtractedTable] = []
        combined = self._filter_candidate_tables(self._extract_combined_tables(report_file, doc))
        combined_names = {item.table_name for item in combined}
        extracted.extend(combined)
        for page_index in range(len(doc)):
            page = doc[page_index]
            text = page.get_text() or ""
            for table_name, keywords in TABLE_KEYWORDS.items():
                if table_name in combined_names:
                    continue
                if not any(keyword in text for keyword in keywords):
                    continue
                if not self._page_is_candidate(text, table_name):
                    continue
                extracted.extend(self._extract_tables_from_page(page, table_name, report_file.source_path))
        return self._filter_candidate_tables(extracted)

    def _extract_combined_tables(self, report_file: ReportFile, doc: fitz.Document) -> list[ExtractedTable]:
        combined_specs = {
            "balance_sheet": {
                "start": ["合并资产负债表", "1、合并资产负债表"],
                "stop": ["母公司资产负债表", "2、母公司资产负债表", "3、合并利润表", "合并利润表"],
                "max_span": 6,
            },
            "income_sheet": {
                "start": ["合并利润表", "3、合并利润表"],
                "stop": ["母公司利润表", "4、合并现金流量表", "合并现金流量表"],
                "max_span": 5,
            },
            "cash_flow_sheet": {
                "start": ["合并现金流量表", "5、合并现金流量表", "4、合并现金流量表"],
                "stop": ["母公司现金流量表", "合并所有者权益变动表"],
                "max_span": 5,
            },
            "core_performance_indicators_sheet": {
                "start": ["主要会计数据和财务指标", "主要会计数据", "主要财务指标"],
                "stop": ["第三节", "资产及负债状况分析", "财务报告"],
                "max_span": 3,
            },
        }
        results: list[ExtractedTable] = []
        for table_name, spec in combined_specs.items():
            page_indexes = self._find_page_range(doc, table_name, spec["start"], spec["stop"], spec["max_span"])
            if not page_indexes:
                continue
            df = self._combine_pdfplumber_tables(Path(report_file.source_path), page_indexes)
            unit_hint = self._guess_unit(doc[page_indexes[0]])
            if not df.empty and self._table_quality_score(table_name, df) >= self._quality_threshold(table_name):
                results.append(
                    ExtractedTable(
                        table_name=table_name,
                        page_number=page_indexes[0] + 1,
                        source_method="pdfplumber.combined_pages",
                        dataframe=df,
                        raw_title="combined_pages",
                        unit_hint=unit_hint,
                    )
                )
            text_df = self._combine_text_lines(doc, page_indexes)
            if not text_df.empty and self._table_quality_score(table_name, text_df) >= max(2.0, self._quality_threshold(table_name) - 1.0):
                results.append(
                    ExtractedTable(
                        table_name=table_name,
                        page_number=page_indexes[0] + 1,
                        source_method="fitz.combined_text",
                        dataframe=text_df,
                        raw_title="combined_text",
                        unit_hint=unit_hint,
                    )
                )
        return results

    def _find_page_range(
        self,
        doc: fitz.Document,
        table_name: str,
        start_markers: list[str],
        stop_markers: list[str],
        max_span: int,
    ) -> list[int]:
        start_index = None
        for i in range(len(doc)):
            text = doc[i].get_text() or ""
            if any(marker in text for marker in start_markers) and self._page_is_candidate(text, table_name):
                start_index = i
                break
        if start_index is None:
            return []

        pages = [start_index]
        for i in range(start_index + 1, min(len(doc), start_index + max_span)):
            text = doc[i].get_text() or ""
            if any(marker in text for marker in stop_markers):
                pages.append(i)
                break
            pages.append(i)
        return pages

    def _combine_pdfplumber_tables(self, pdf_path: Path, page_indexes: list[int]) -> pd.DataFrame:
        rows: list[list[object]] = []
        if pdfplumber is None:
            return pd.DataFrame()
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_index in page_indexes:
                    page = pdf.pages[page_index]
                    for table in page.extract_tables() or []:
                        for row in table:
                            if row and any(cell not in (None, "") for cell in row):
                                rows.append(row)
        except Exception:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def _combine_text_lines(self, doc: fitz.Document, page_indexes: list[int]) -> pd.DataFrame:
        rows: list[list[str]] = []
        for page_index in page_indexes:
            text = doc[page_index].get_text() or ""
            for line in text.splitlines():
                raw = line.strip()
                if not raw:
                    continue
                rows.append(self._inline_text_row(raw))
        return pd.DataFrame(rows)

    def _extract_tables_from_page(self, page: fitz.Page, table_name: str, pdf_path: str) -> list[ExtractedTable]:
        results: list[ExtractedTable] = []
        try:
            tables = page.find_tables()
        except Exception:
            tables = None

        if tables and getattr(tables, "tables", None):
            for idx, table in enumerate(tables.tables[: self.max_tables_per_page]):
                try:
                    matrix = table.extract()
                    df = pd.DataFrame(matrix)
                except Exception:
                    continue
                if df.empty:
                    continue
                results.append(
                    ExtractedTable(
                        table_name=table_name,
                        page_number=page.number + 1,
                        source_method=f"pymupdf.find_tables[{idx}]",
                        dataframe=df,
                        raw_title=self._guess_title(page),
                        unit_hint=self._guess_unit(page),
                    )
                )

        if results:
            filtered = self._filter_candidate_tables(results)
            if filtered:
                return filtered

        if pdfplumber is not None:
            results.extend(self._extract_with_pdfplumber(Path(pdf_path), page.number, table_name))
            filtered = self._filter_candidate_tables(results)
            if filtered:
                return filtered

        if camelot is not None:
            results.extend(self._extract_with_camelot(Path(pdf_path), page.number, table_name))
            filtered = self._filter_candidate_tables(results)
            if filtered:
                return filtered

        fallback_df = self._extract_key_value_lines(page)
        if not fallback_df.empty and self._table_quality_score(table_name, fallback_df) >= max(2.0, self._quality_threshold(table_name) - 1.0):
            results.append(
                ExtractedTable(
                    table_name=table_name,
                    page_number=page.number + 1,
                    source_method="text_fallback",
                    dataframe=fallback_df,
                    raw_title=self._guess_title(page),
                    unit_hint=self._guess_unit(page),
                )
            )
        return results

    def _extract_with_pdfplumber(self, pdf_path: Path, page_index: int, table_name: str) -> list[ExtractedTable]:
        results: list[ExtractedTable] = []
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                page = pdf.pages[page_index]
                tables = page.extract_tables() or []
                for idx, table in enumerate(tables[: self.max_tables_per_page]):
                    df = pd.DataFrame(table)
                    if df.empty:
                        continue
                    results.append(
                        ExtractedTable(
                            table_name=table_name,
                            page_number=page_index + 1,
                            source_method=f"pdfplumber.extract_tables[{idx}]",
                            dataframe=df,
                            raw_title=None,
                            unit_hint=None,
                        )
                    )
        except Exception:
            return []
        return results

    def _extract_with_camelot(self, pdf_path: Path, page_index: int, table_name: str) -> list[ExtractedTable]:
        results: list[ExtractedTable] = []
        if camelot is None:
            return results
        try:
            tables = camelot.read_pdf(str(pdf_path), pages=str(page_index + 1), flavor="stream")
        except Exception:
            return results
        for idx in range(min(self.max_tables_per_page, getattr(tables, "n", 0))):
            try:
                df = tables[idx].df
            except Exception:
                continue
            if df is None or df.empty:
                continue
            results.append(
                ExtractedTable(
                    table_name=table_name,
                    page_number=page_index + 1,
                    source_method=f"camelot.stream[{idx}]",
                    dataframe=df,
                    raw_title=None,
                    unit_hint=None,
                )
            )
        return results

    def _guess_title(self, page: fitz.Page) -> str | None:
        text = page.get_text() or ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(key in line for keys in TABLE_KEYWORDS.values() for key in keys):
                return line
        return None

    def _guess_unit(self, page: fitz.Page) -> str | None:
        text = page.get_text() or ""
        for snippet in text.splitlines()[:20]:
            unit = detect_unit(snippet)
            if unit:
                return unit
        return None

    def _extract_key_value_lines(self, page: fitz.Page) -> pd.DataFrame:
        text = page.get_text() or ""
        rows: list[list[str]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if len(raw) < 4:
                continue
            rows.append(self._inline_text_row(raw))
        return pd.DataFrame(rows)

    def _page_is_candidate(self, text: str, table_name: str) -> bool:
        normalized = clean_label(text)
        if "目录" in normalized and "财务报告" not in normalized:
            return False
        digit_count = sum(ch.isdigit() for ch in text)
        alias_hits = 0
        for alias in FIELD_ALIASES.get(table_name, {}):
            if clean_label(alias) in normalized:
                alias_hits += 1
        if table_name == "core_performance_indicators_sheet":
            return alias_hits >= 2 or digit_count >= 80
        return alias_hits >= 1 or digit_count >= 80

    def _inline_text_row(self, raw: str) -> list[str]:
        numeric_pattern = r"[-＋+－]?\(?\d[\d,，]*(?:\.\d+)?\)?(?:%|亿元|万元|元|百分点)?"
        numeric_texts = [match.group(0) for match in re.finditer(numeric_pattern, raw)]
        label = re.sub(numeric_pattern, " ", raw)
        label = " ".join(label.split()).strip()
        if not numeric_texts:
            return [raw]
        return [label or raw, *numeric_texts[:5]]

    def _filter_candidate_tables(self, candidates: list[ExtractedTable]) -> list[ExtractedTable]:
        if not candidates:
            return []
        grouped: dict[tuple[str, int], list[tuple[float, ExtractedTable]]] = {}
        for item in candidates:
            score = self._table_quality_score(item.table_name, item.dataframe)
            key = (item.table_name, item.page_number)
            grouped.setdefault(key, []).append((score, item))

        filtered: list[ExtractedTable] = []
        for (table_name, _), scored_items in grouped.items():
            threshold = self._quality_threshold(table_name)
            scored_items = sorted(scored_items, key=lambda pair: pair[0], reverse=True)
            kept = [item for score, item in scored_items if score >= threshold][:2]
            if not kept and scored_items:
                best_score, best_item = scored_items[0]
                if best_score >= max(2.0, threshold - 1.0):
                    kept = [best_item]
            filtered.extend(kept)
        return filtered

    def _table_quality_score(self, table_name: str, dataframe: pd.DataFrame) -> float:
        df = dataframe.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return 0.0
        alias_hits: set[str] = set()
        numeric_cells = 0
        nonempty_cells = 0
        for _, row in df.head(120).iterrows():
            cells = ["" if pd.isna(v) else str(v).strip() for v in row.tolist()]
            joined = clean_label("".join(cells[:3]))
            for alias in FIELD_ALIASES.get(table_name, {}):
                normalized_alias = clean_label(alias)
                if normalized_alias and normalized_alias in joined:
                    alias_hits.add(normalized_alias)
            for cell in cells:
                if not cell:
                    continue
                nonempty_cells += 1
                if parse_numeric(cell, None) is not None and any(ch.isdigit() for ch in cell):
                    numeric_cells += 1
        numeric_density = numeric_cells / max(nonempty_cells, 1)
        row_count_score = min(len(df) / 8.0, 4.0)
        alias_score = min(len(alias_hits), 8) * 1.5
        density_score = min(numeric_density * 6.0, 4.0)
        return alias_score + density_score + row_count_score

    def _quality_threshold(self, table_name: str) -> float:
        if table_name == "core_performance_indicators_sheet":
            return 5.0
        return 4.5


def load_report_manifest(csv_path: Path, exchange: str) -> list[ReportFile]:
    df = pd.read_csv(csv_path)
    if "selected" in df.columns:
        df = df[df["selected"].fillna(False).astype(bool)]
    if "is_english_version" in df.columns:
        df = df[~df["is_english_version"].fillna(False).astype(bool)]

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        text = str(v).strip()
        return text if text.lower() != "nan" else None

    files: list[ReportFile] = []
    for row in df.to_dict(orient="records"):
        stock_code = _clean(row.get("stock_code"))
        if stock_code is not None:
            stock_code = stock_code.split(".")[0].zfill(6)
        files.append(
            ReportFile(
                exchange=exchange,
                source_name=_clean(row.get("source_name")),
                source_path=_clean(row.get("source_path")),
                stock_code=stock_code,
                stock_abbr=_clean(row.get("company_norm")) or _clean(row.get("stock_abbr")),
                report_date=_clean(row.get("report_date")),
                report_year=int(_clean(row.get("report_year") or row.get("year"))) if _clean(row.get("report_year") or row.get("year")) is not None else None,
                report_period=_clean(row.get("period_norm")) or _clean(row.get("report_period")),
                report_type=_clean(row.get("report_type")),
            )
        )
    return files
