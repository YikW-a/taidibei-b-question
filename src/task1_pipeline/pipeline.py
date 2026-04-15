from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from .config import PipelineConfig
from .db import DatabaseManager
from .evaluate import ExtractionEvaluator
from .extractor import PDFExtractor, load_report_manifest
from .metadata import enrich_report_with_company_info, load_company_lookup, load_company_lookup_by_abbr
from .models import StandardizedRecord
from .quality_review import build_quality_review_frames, write_quality_review_report
from .transform import (
    TableTransformer,
    consolidate_records,
    enrich_consolidated_records,
    records_to_dataframes,
    sanitize_consolidated_records,
)
from .validator import DataValidator


class Task1Pipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.extractor = PDFExtractor()
        self.transformer = TableTransformer()
        self.validator = DataValidator()
        self.db = DatabaseManager(config.database_url)
        self.evaluator = ExtractionEvaluator()

    def run(self) -> dict[str, object]:
        self._ensure_dirs()
        reports = self._load_reports()
        if self.config.sample_limit:
            reports = self._sample_reports(reports, self.config.sample_limit)

        standardized_records: list[StandardizedRecord] = []
        extraction_logs: list[dict[str, object]] = []

        progress = tqdm(reports, desc="Processing reports", unit="report")
        for report in progress:
            progress.set_postfix_str(report.source_name[:40])
            extracted_tables = self.extractor.extract(report)
            for table in extracted_tables:
                transformed = self.transformer.transform(report, table)
                standardized_records.extend(transformed)
                for item in transformed:
                    extraction_logs.append(
                        {
                            "source_name": report.source_name,
                            "table_name": item.table_name,
                            "page_number": item.page_number,
                            "source_method": item.source_method,
                            "warning_text": ";".join(item.warnings),
                        }
                    )

        validation_issues = self.validator.validate_records(standardized_records)
        consolidated_records = consolidate_records(standardized_records)
        consolidated_records = enrich_consolidated_records(consolidated_records)
        consolidated_records = sanitize_consolidated_records(consolidated_records)
        validation_issues = self.validator.validate_records(consolidated_records)
        dataframes = records_to_dataframes(consolidated_records)
        validation_df = self.validator.issues_to_dataframe(validation_issues)
        manifest_df = pd.DataFrame([report.__dict__ for report in reports])
        extraction_df = pd.DataFrame(extraction_logs)
        consolidated_df = pd.DataFrame(
            [
                {
                    "table_name": r.table_name,
                    "source_name": r.source_name,
                    "report_type": r.report_type,
                    "page_number": r.page_number,
                    "source_method": r.source_method,
                    "warning_text": ";".join(r.warnings),
                    **r.values,
                }
                for r in consolidated_records
            ]
        )

        self.db.create_all()
        for table_name, df in dataframes.items():
            self.db.write_dataframe(table_name, df)
            self._write_artifact_csv(df, f"{table_name}.csv")
            self._write_final_table_csv(df, f"{table_name}.csv")

        self.db.write_dataframe("report_file_manifest", manifest_df)
        self.db.write_dataframe("extraction_log", extraction_df)
        self.db.write_dataframe("validation_log", validation_df)

        self._write_artifact_csv(manifest_df, "report_file_manifest.csv")
        self._write_artifact_csv(extraction_df, "extraction_log.csv")
        self._write_artifact_csv(consolidated_df, "consolidated_records.csv")
        self._write_artifact_csv(validation_df, "validation_log.csv")

        summary = self.evaluator.summarize(consolidated_records, validation_issues)
        coverage_df, missing_df = self.evaluator.build_field_coverage_frames(consolidated_records)
        missing_reason_detail_df, missing_reason_summary_df = self.evaluator.build_missing_reason_frames(consolidated_records)
        quality_anomaly_df, quality_field_summary_df = build_quality_review_frames(consolidated_records, validation_issues)
        coverage_summary = self.evaluator.summarize_coverage(coverage_df)
        reason_summary = self.evaluator.summarize_missing_reasons(missing_reason_summary_df)
        summary.update(coverage_summary)
        summary.update(reason_summary)
        self._write_artifact_csv(coverage_df, "field_coverage.csv")
        self._write_artifact_csv(missing_df, "missing_field_stats.csv")
        self._write_artifact_csv(missing_reason_detail_df, "missing_reason_detail.csv")
        self._write_artifact_csv(missing_reason_summary_df, "missing_reason_stats.csv")
        self._write_artifact_csv(quality_anomaly_df, "database_quality_anomalies.csv")
        self._write_artifact_csv(quality_field_summary_df, "database_quality_field_summary.csv")
        self.evaluator.write_summary(summary, self.config.evaluation_dir / "summary.json")
        self.evaluator.write_quality_report(
            summary,
            coverage_df,
            missing_reason_summary_df,
            self.config.evaluation_dir / "quality_report.md",
        )
        write_quality_review_report(
            summary,
            quality_anomaly_df,
            quality_field_summary_df,
            self.config.evaluation_dir / "database_quality_review.md",
        )
        self.evaluator.write_manual_audit_workbook(
            consolidated_records,
            coverage_df,
            self.config.evaluation_dir / "manual_audit_template.xlsx",
        )
        self.evaluator.write_paper_outputs(
            summary,
            coverage_df,
            missing_reason_summary_df,
            self.config.evaluation_dir,
        )
        self._write_run_meta(summary)
        return summary

    def _ensure_dirs(self) -> None:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.config.evaluation_dir.mkdir(parents=True, exist_ok=True)
        (self.config.output_dir / "final_tables").mkdir(parents=True, exist_ok=True)

    def _load_reports(self):
        reports = []
        company_lookup = load_company_lookup(self.config.company_info_path)
        company_lookup_by_abbr = load_company_lookup_by_abbr(self.config.company_info_path)
        sse_candidates = [
            self.config.input_manifest_sse,
            self.config.base_dir / "正式数据/附件2：财务报告/reports-上交所/sse_reports_manifest.csv",
        ]
        szse_candidates = [
            self.config.input_manifest_szse,
            self.config.base_dir / "正式数据/附件2：财务报告/reports-深交所/szse_reports_manifest.csv",
        ]
        for candidate in sse_candidates:
            if candidate.exists():
                reports.extend(load_report_manifest(candidate, exchange="SSE"))
                break
        for candidate in szse_candidates:
            if candidate.exists():
                reports.extend(load_report_manifest(candidate, exchange="SZSE"))
                break
        return [enrich_report_with_company_info(report, company_lookup, company_lookup_by_abbr) for report in reports]

    def _write_artifact_csv(self, dataframe: pd.DataFrame, name: str) -> None:
        output = self.config.artifacts_dir / name
        dataframe.to_csv(output, index=False, encoding="utf-8-sig")

    def _write_final_table_csv(self, dataframe: pd.DataFrame, name: str) -> None:
        output = self.config.output_dir / "final_tables" / name
        dataframe.to_csv(output, index=False, encoding="utf-8-sig")

    def _write_run_meta(self, summary: dict[str, object]) -> None:
        meta = {
            "database_url": self.config.database_url,
            "input_manifest_sse": str(self.config.input_manifest_sse),
            "input_manifest_szse": str(self.config.input_manifest_szse),
            "sample_limit": self.config.sample_limit,
            "summary": summary,
        }
        with (self.config.logs_dir / "run_meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _sample_reports(self, reports, limit: int):
        by_exchange: dict[str, list] = {}
        for report in reports:
            by_exchange.setdefault(report.exchange, []).append(report)

        selected = []
        seen_stock_codes = set()
        exchanges = sorted(by_exchange.keys())
        positions = {exchange: 0 for exchange in exchanges}

        while len(selected) < limit:
            progressed = False
            for exchange in exchanges:
                bucket = by_exchange[exchange]
                while positions[exchange] < len(bucket):
                    report = bucket[positions[exchange]]
                    positions[exchange] += 1
                    stock_code = report.stock_code or report.stock_abbr or report.source_name.split("：")[0]
                    if stock_code in seen_stock_codes:
                        continue
                    selected.append(report)
                    seen_stock_codes.add(stock_code)
                    progressed = True
                    break
                if len(selected) >= limit:
                    break
            if not progressed:
                break

        if len(selected) < limit:
            for report in reports:
                if len(selected) >= limit:
                    break
                if report in selected:
                    continue
                selected.append(report)
        return selected[:limit]
