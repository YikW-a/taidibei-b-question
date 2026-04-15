from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, create_engine


TABLE_SCHEMAS: dict[str, list[tuple[str, object]]] = {
    "core_performance_indicators_sheet": [
        ("serial_number", Integer),
        ("stock_code", String(20)),
        ("stock_abbr", String(50)),
        ("eps", Float),
        ("total_operating_revenue", Float),
        ("operating_revenue_yoy_growth", Float),
        ("operating_revenue_qoq_growth", Float),
        ("net_profit_10k_yuan", Float),
        ("net_profit_yoy_growth", Float),
        ("net_profit_qoq_growth", Float),
        ("net_asset_per_share", Float),
        ("roe", Float),
        ("operating_cf_per_share", Float),
        ("net_profit_excl_non_recurring", Float),
        ("net_profit_excl_non_recurring_yoy", Float),
        ("gross_profit_margin", Float),
        ("net_profit_margin", Float),
        ("roe_weighted_excl_non_recurring", Float),
        ("report_period", String(20)),
        ("report_year", Integer),
    ],
    "balance_sheet": [
        ("serial_number", Integer),
        ("stock_code", String(20)),
        ("stock_abbr", String(50)),
        ("asset_cash_and_cash_equivalents", Float),
        ("asset_accounts_receivable", Float),
        ("asset_inventory", Float),
        ("asset_trading_financial_assets", Float),
        ("asset_construction_in_progress", Float),
        ("asset_total_assets", Float),
        ("asset_total_assets_yoy_growth", Float),
        ("liability_accounts_payable", Float),
        ("liability_advance_from_customers", Float),
        ("liability_total_liabilities", Float),
        ("liability_total_liabilities_yoy_growth", Float),
        ("liability_contract_liabilities", Float),
        ("liability_short_term_loans", Float),
        ("asset_liability_ratio", Float),
        ("equity_unappropriated_profit", Float),
        ("equity_total_equity", Float),
        ("report_period", String(20)),
        ("report_year", Integer),
    ],
    "cash_flow_sheet": [
        ("serial_number", Integer),
        ("stock_code", String(20)),
        ("stock_abbr", String(50)),
        ("net_cash_flow", Float),
        ("net_cash_flow_yoy_growth", Float),
        ("operating_cf_net_amount", Float),
        ("operating_cf_ratio_of_net_cf", Float),
        ("operating_cf_cash_from_sales", Float),
        ("investing_cf_net_amount", Float),
        ("investing_cf_ratio_of_net_cf", Float),
        ("investing_cf_cash_for_investments", Float),
        ("investing_cf_cash_from_investment_recovery", Float),
        ("financing_cf_cash_from_borrowing", Float),
        ("financing_cf_cash_for_debt_repayment", Float),
        ("financing_cf_net_amount", Float),
        ("financing_cf_ratio_of_net_cf", Float),
        ("report_period", String(20)),
        ("report_year", Integer),
    ],
    "income_sheet": [
        ("serial_number", Integer),
        ("stock_code", String(20)),
        ("stock_abbr", String(50)),
        ("net_profit", Float),
        ("net_profit_yoy_growth", Float),
        ("other_income", Float),
        ("total_operating_revenue", Float),
        ("operating_revenue_yoy_growth", Float),
        ("operating_expense_cost_of_sales", Float),
        ("operating_expense_selling_expenses", Float),
        ("operating_expense_administrative_expenses", Float),
        ("operating_expense_financial_expenses", Float),
        ("operating_expense_rnd_expenses", Float),
        ("operating_expense_taxes_and_surcharges", Float),
        ("total_operating_expenses", Float),
        ("operating_profit", Float),
        ("total_profit", Float),
        ("asset_impairment_loss", Float),
        ("credit_impairment_loss", Float),
        ("report_period", String(20)),
        ("report_year", Integer),
    ],
}


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url)
        self.metadata = MetaData()
        self.tables = self._build_tables()

    def _build_tables(self) -> dict[str, Table]:
        tables: dict[str, Table] = {}
        for table_name, columns in TABLE_SCHEMAS.items():
            cols = [Column(col_name, col_type) for col_name, col_type in columns]
            tables[table_name] = Table(table_name, self.metadata, *cols)

        tables["report_file_manifest"] = Table(
            "report_file_manifest",
            self.metadata,
            Column("source_name", String(255)),
            Column("source_path", Text),
            Column("exchange", String(20)),
            Column("stock_code", String(20)),
            Column("stock_abbr", String(100)),
            Column("report_date", String(20)),
            Column("report_year", Integer),
            Column("report_period", String(20)),
            Column("report_type", String(20)),
        )
        tables["extraction_log"] = Table(
            "extraction_log",
            self.metadata,
            Column("source_name", String(255)),
            Column("table_name", String(100)),
            Column("page_number", Integer),
            Column("source_method", String(100)),
            Column("warning_text", Text),
        )
        tables["validation_log"] = Table(
            "validation_log",
            self.metadata,
            Column("severity", String(20)),
            Column("rule_name", String(100)),
            Column("table_name", String(100)),
            Column("source_name", String(255)),
            Column("record_key", String(255)),
            Column("message", Text),
        )
        return tables

    def create_all(self) -> None:
        self.metadata.create_all(self.engine)

    def write_dataframe(self, table_name: str, dataframe: pd.DataFrame) -> None:
        if dataframe.empty:
            return
        dataframe.to_sql(table_name, self.engine, if_exists="append", index=False)

