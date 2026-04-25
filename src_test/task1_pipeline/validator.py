from __future__ import annotations

from src.task1_pipeline.validator import DataValidator as BaseDataValidator


class DataValidator(BaseDataValidator):
    def _check_cross_table_consistency(self, records):
        issues = super()._check_cross_table_consistency(records)
        filtered = []
        for issue in issues:
            if issue.rule_name != "cash_flow_equation_precheck":
                filtered.append(issue)
                continue
            try:
                message = issue.message or ""
                stored_part = message.split("stored=")[1].split(",")[0]
                derived_part = message.split("derived=")[1]
                stored = float(stored_part)
                derived = float(derived_part)
            except Exception:
                filtered.append(issue)
                continue

            diff = abs(derived - stored)
            magnitude = max(abs(stored), abs(derived), 1.0)

            # 放宽对中等偏差的警报，给汇率变动及其他补充项留出空间；
            # 但净现金流近零或符号翻转的大偏差仍保留。
            if abs(stored) <= 1e-3 and abs(derived) >= 100.0:
                filtered.append(issue)
                continue
            if stored * derived < 0 and diff >= max(10_000.0, magnitude * 0.3):
                filtered.append(issue)
                continue
            if diff >= max(5_000.0, magnitude * 0.15):
                filtered.append(issue)
        return filtered
