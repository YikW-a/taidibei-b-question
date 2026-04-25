from __future__ import annotations

import json

import pandas as pd

from src.task1_pipeline.extractor import load_report_manifest
from src.task1_pipeline.models import StandardizedRecord
from src.task1_pipeline.metadata import (
    enrich_report_with_company_info,
    load_company_lookup,
    load_company_lookup_by_abbr,
)
from src.task1_pipeline.pipeline import Task1Pipeline as BaseTask1Pipeline
from src.task1_pipeline.quality_review import build_quality_review_frames, write_quality_review_report
from src.task1_pipeline.transform import (
    consolidate_records,
    enrich_consolidated_records,
    records_to_dataframes,
    sanitize_consolidated_records,
)

from .manifest import build_test_manifests
from .validator import DataValidator


class Task1Pipeline(BaseTask1Pipeline):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.validator = DataValidator()

    def _load_reports(self):
        build_test_manifests(
            base_dir=self.config.base_dir,
            output_dir=self.config.output_dir,
            company_info_path=self.config.company_info_path,
        )
        reports = []
        company_lookup = load_company_lookup(self.config.company_info_path)
        company_lookup_by_abbr = load_company_lookup_by_abbr(self.config.company_info_path)
        for candidate, exchange in [
            (self.config.input_manifest_sse, "SSE"),
            (self.config.input_manifest_szse, "SZSE"),
        ]:
            if candidate.exists():
                reports.extend(load_report_manifest(candidate, exchange=exchange))
        return [enrich_report_with_company_info(report, company_lookup, company_lookup_by_abbr) for report in reports]

    def run(self) -> dict[str, object]:
        self._ensure_dirs()
        reports = self._load_reports()
        if self.config.sample_limit:
            reports = self._sample_reports(reports, self.config.sample_limit)

        standardized_records: list[StandardizedRecord] = []
        extraction_logs: list[dict[str, object]] = []

        from tqdm import tqdm

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

        consolidated_records = consolidate_records(standardized_records)
        consolidated_records = enrich_consolidated_records(consolidated_records)
        consolidated_records = sanitize_consolidated_records(consolidated_records)
        self._repair_cash_flow_records(consolidated_records)

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

    def _repair_cash_flow_records(self, records: list[StandardizedRecord]) -> None:
        for record in records:
            if record.table_name != "cash_flow_sheet":
                continue
            values = record.values
            operating = self._safe_float(values.get("operating_cf_net_amount"))
            investing = self._safe_float(values.get("investing_cf_net_amount"))
            financing = self._safe_float(values.get("financing_cf_net_amount"))
            net_cash = self._safe_float(values.get("net_cash_flow"))
            derived = None
            if None not in (operating, investing, financing):
                derived = operating + investing + financing

            replaced_net_cash = False
            if derived is not None and self._should_override_net_cash(net_cash, derived, operating, investing, financing):
                values["net_cash_flow"] = derived
                net_cash = derived
                replaced_net_cash = True

            if net_cash in (None, 0):
                continue
            for amount_field, ratio_field in [
                ("operating_cf_net_amount", "operating_cf_ratio_of_net_cf"),
                ("investing_cf_net_amount", "investing_cf_ratio_of_net_cf"),
                ("financing_cf_net_amount", "financing_cf_ratio_of_net_cf"),
            ]:
                amount = self._safe_float(values.get(amount_field))
                if amount is None:
                    continue
                derived_ratio = amount / net_cash * 100
                current_ratio = self._safe_float(values.get(ratio_field))
                if (
                    replaced_net_cash
                    or current_ratio is None
                    or abs(current_ratio) > 1000
                    or abs(current_ratio - derived_ratio) > max(10.0, abs(derived_ratio) * 0.2)
                ):
                    values[ratio_field] = derived_ratio

    def _should_override_net_cash(
        self,
        current: float | None,
        derived: float,
        operating: float | None,
        investing: float | None,
        financing: float | None,
    ) -> bool:
        if current is None:
            return True
        component_scale = max(abs(operating or 0.0), abs(investing or 0.0), abs(financing or 0.0), abs(derived))
        if abs(current) <= 1e-3 and component_scale >= 100.0:
            return True
        if abs(current) <= 1.0 and component_scale >= 10_000.0:
            return True
        return False

    def _safe_float(self, value):
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except Exception:
            return None
        if pd.isna(numeric):
            return None
        return numeric

    def _write_run_meta(self, summary: dict[str, object]) -> None:
        meta = {
            "database_url": self.config.database_url,
            "input_manifest_sse": str(self.config.input_manifest_sse),
            "input_manifest_szse": str(self.config.input_manifest_szse),
            "sample_limit": self.config.sample_limit,
            "summary": summary,
            "test_cash_flow_repairs": {
                "override_near_zero_net_cash": True,
                "relaxed_cash_flow_equation_validator": True,
            },
        }
        with (self.config.logs_dir / "run_meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
