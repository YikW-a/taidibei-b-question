# 任务一使用说明

## 1. 任务概述

任务一的目标是从附件 2 的上市公司财务报告 PDF 中抽取四类目标表信息，完成字段映射、单位统一、数据校验，并写入数据库，同时输出抽取质量评估结果。

当前程序已经覆盖以下主流程：

1. 财报目录预处理
2. PDF 表格与文本抽取
3. 字段映射与单位换算
4. 跨表补值与派生指标计算
5. 入库前异常值清洗与一致性校验
6. SQLite / MySQL 入库
7. 抽取质量评估
8. 缺失原因分析
9. 数据库质量复核
10. 人工抽样核验模板生成
11. 论文结果表与文字稿生成
12. 会计勾稽校验与通过率统计

当前最新版已在正式数据上完成一次全量运行，最终结果为：

- 有效处理报告数：`1235`
- 主记录总数：`3290`
- 四张业务表记录数：
  - `balance_sheet`: `820`
  - `cash_flow_sheet`: `823`
  - `core_performance_indicators_sheet`: `824`
  - `income_sheet`: `823`
- 当前校验结果：`error = 0`，仅剩 `17` 条 `warning`

当前任务一已经完成从“可运行”到“有质量约束”的过渡，后续重点是继续提质而不是重搭框架，主要集中在：

1. 严格按附件 3 区分字段的直读、复用与计算来源
2. 优化提取阶段，减少错页、错列、错值
3. 回头治理会污染任务二排序、均值与筛选的异常值
4. 继续降低 `balance_sheet` 横向空缺和 KPI 极端比例值

当前还需要额外记住一点：

- 任务一不再只服务任务二，任务三的 SQL 查询层同样直接依赖 `outputs/task1/task1_financials.db`
- 因此任务一里的异常金额、异常比例、缺失值和口径问题，会同时污染任务二与任务三

## 2. 程序入口

- 主入口: [run_task1.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task1.py)
- 命令行封装: [src/task1_pipeline/cli.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/cli.py)

默认运行方式：

```bash
python3 run_task1.py
```

仅抽样运行前 `N` 份报告：

```bash
python3 run_task1.py --sample-limit 30
```

指定输出目录：

```bash
python3 run_task1.py --output-dir outputs/task1_debug
```

## 3. 建议运行顺序

### 第一步：预处理上交所与深交所目录

```bash
python3 scripts/process_sse_reports.py
python3 scripts/process_szse_reports.py
```

这一步会生成两份处理后的目录和清单文件：

- `正式数据/附件2：财务报告/reports-上交所_处理后`
- `正式数据/附件2：财务报告/reports-深交所_处理后`

### 第二步：加载运行环境

如果本机使用了 `camelot`、`paddleocr` 等依赖，建议先执行：

```bash
source scripts/task1_env.sh
```

这个脚本会把缓存目录重定向到项目内部，避免 matplotlib / paddlex 的权限问题。

### 第三步：运行任务一主程序

```bash
python3 run_task1.py
```

快速抽样验证：

```bash
python3 run_task1.py --sample-limit 10
```

### 第四步：执行会计勾稽校验

在主程序完成入库后，可继续运行数据库级勾稽校验脚本：

```bash
python3 scripts/check_task1_accounting_consistency.py
```

如果任务一结果已经写入 MySQL，可显式传入连接串：

```bash
python3 scripts/check_task1_accounting_consistency.py \
  --database-url "mysql+pymysql://root:password@127.0.0.1:3306/task1_db?charset=utf8mb4"
```

该脚本会基于数据库中的四张业务表输出通过率、失败率和失败样例，默认结果目录为 `outputs/task1/accounting_checks/`。

如果不重跑全量抽取、只想从既有 SQLite 或 MySQL 数据库重新导出最终提交表，可以执行：

```bash
python3 scripts/export_task1_final_tables.py
```

## 4. 功能覆盖

当前版本已经实现以下能力：

### 4.1 PDF 文本与表格抽取

- 使用 `PyMuPDF` 读取 PDF 页面与表格区域
- 使用 `pdfplumber` 抽取跨页表格
- 使用 `camelot` 作为补充表格抽取方案
- 使用 `fitz.combined_text` 兜底拆行文本与续表内容
- 自动定位：
  - `核心业绩指标表`
  - `资产负债表`
  - `现金流量表`
  - `利润表`

### 4.2 字段映射与单位统一

- 支持四张目标表的中文别名映射
- 自动识别并统一：
  - `元`
  - `万元`
  - `亿元`
  - `%`
- 自动处理负数、括号负数、百分点、空值符号

### 4.3 派生指标与跨表补值

- 自动计算：
  - `资产总计同比增长`
  - `负债合计同比增长`
  - `资产负债率`
  - `净现金流同比增长`
  - `现金流占比`
- 从利润表、资产负债表、现金流量表回填核心业绩指标表字段
- 在条件充分时推导：
  - `每股净资产`
  - `每股经营现金流`
  - `扣非加权平均净资产收益率`
  - `营业总收入环比增长`
  - `归母净利润环比增长`
- 会按附件 3 的字段来源约束执行：
  - `营业总收入 / 归母净利润` 优先复用利润表
  - `资产负债率 / 现金流占比 / 毛利率 / 净利率 / ROE` 优先按公式计算
  - `operating_revenue_qoq_growth / net_profit_qoq_growth` 会按同公司同年份的累计披露值先还原为单季度值，再计算环比

### 4.4 数据校验

- 必填字段检查
- 业务主键重复检查
- 百分比 / 增长率异常值检查
- 入库前极端金额 / 极端比例清洗
- 资产负债、现金流、毛利率、净利率、ROE 的跨表一致性预校验
- 资产负债与现金流勾稽所需的派生补值
- 输出 `validation_log`

### 4.5 数据库质量复核

- 自动扫描入库前记录中的极端金额与极端比例字段
- 汇总高频异常字段、异常样例和校验告警热点
- 输出独立的数据库质量复核清单与 Markdown 报告
- 便于直接对照任务二中暴露出的异常问答结果回溯到任务一数据层

### 4.5.1 当前已知问题与边界

- `operating_revenue_qoq_growth`、`net_profit_qoq_growth` 已接入按累计披露口径还原单季度后再计算的逻辑，但正式全量结果需要在最新代码下重跑后才能完全体现。
- `balance_sheet` 横向空缺仍是当前重点问题，部分来自 PDF 表格抽取失败，部分来自错列或候选表质量不稳。
- 某些异常金额值与异常比例值更像提取错位，而不只是企业真实极端经营情况。
- 任务一的异常值会直接污染任务二的排序、均值和图表，因此任务二暴露的异常问答要优先回溯任务一。

### 4.6 会计勾稽校验

- 基于已入库的四张业务表做二次逻辑校验
- 自动检验：
  - `总资产 = 总负债 + 所有者权益`
  - `资产负债率 = 总负债 / 总资产`
  - `净现金流 = 经营 + 投资 + 筹资`
  - 三类现金流占比与净现金流的一致性
  - 毛利率、净利率、ROE 与跨表结果的一致性
  - 每股净资产、每股经营现金流与推导结果的一致性
- 输出通过率、失败率与失败样例

### 4.7 数据库入库

- 默认写入 SQLite
- 可切换写入 MySQL
- 自动创建：
  - 四张业务表
  - 三张日志表

### 4.8 评估与交付材料

- 字段覆盖率统计
- 缺失字段统计
- 缺失原因判定
- 质检报告输出
- 人工抽样核验模板输出
- 论文结果表输出
- 论文结果文字稿输出

## 5. 每个程序 / 模块的功能

### 5.1 预处理脚本

- [scripts/process_sse_reports.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/scripts/process_sse_reports.py)
  - 处理上交所 PDF
  - 解析文件名
  - 复制 / 硬链接原始文件到处理后目录
  - 生成 `sse_reports_manifest.csv` 和 `json`

- [scripts/process_szse_reports.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/scripts/process_szse_reports.py)
  - 处理深交所 PDF
  - 规范 `摘要 / 全文 / 更正后 / 更新后`
  - 更正版优先保留
  - 生成 `szse_reports_manifest.csv` 和 `json`

- [scripts/check_task1_accounting_consistency.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/scripts/check_task1_accounting_consistency.py)
  - 基于 SQLite 或 MySQL 数据库执行会计勾稽校验
  - 统计每条规则的可判定样本数、通过率与失败率
  - 输出失败明细和 Markdown 质检报告

- [scripts/export_task1_final_tables.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/scripts/export_task1_final_tables.py)
  - 从已有 SQLite 或 MySQL 数据库重新导出四张最终业务表
  - 自动按附件 3 字段顺序补齐缺失列
  - 适合在不重跑全量抽取的情况下刷新最终提交表

### 5.2 任务一主程序

- [run_task1.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task1.py)
  - 程序总入口
  - 调用 `cli.py`

### 5.3 管道模块

- [src/task1_pipeline/cli.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/cli.py)
  - 解析命令行参数
  - 组织配置并启动主流程

- [src/task1_pipeline/config.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/config.py)
  - 管理输入目录、输出目录、数据库连接串等配置

- [src/task1_pipeline/models.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/models.py)
  - 定义 `ReportFile`、`ExtractedTable`、`StandardizedRecord` 等数据结构

- [src/task1_pipeline/metadata.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/metadata.py)
  - 从封面或附件 1 中补齐公司代码、简称、报告期等元数据

- [src/task1_pipeline/extractor.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/extractor.py)
  - 核心抽取器
  - 负责跨页表格抽取、表格 fallback、文本兜底抽取

- [src/task1_pipeline/mappings.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/mappings.py)
  - 定义四张表的字段别名与表定位关键词

- [src/task1_pipeline/field_rules.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/field_rules.py)
  - 按附件 3 约束字段来源
  - 标注字段应直读、复用还是计算

- [src/task1_pipeline/normalizers.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/normalizers.py)
  - 标签清洗
  - 数值解析
  - 单位统一
  - 报告期标准化

- [src/task1_pipeline/transform.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/transform.py)
  - 把抽取结果转换成目标表记录
  - 做字段映射、派生计算、候选记录合并、跨表补值、入库前异常值清洗

- [src/task1_pipeline/validator.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/validator.py)
  - 做业务校验
  - 生成 `validation_log`
  - 增加跨表一致性预校验

- [src/task1_pipeline/db.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/db.py)
  - 定义数据库表结构
  - 完成 SQLite / MySQL 写入

- [src/task1_pipeline/evaluate.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/evaluate.py)
  - 输出覆盖率统计
  - 输出缺失原因分析
  - 生成质检报告、人工核验模板、论文结果表与文字稿

- [src/task1_pipeline/quality_review.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/quality_review.py)
  - 输出数据库质量复核异常清单
  - 汇总高频异常字段和入库前校验热点
  - 生成 `database_quality_review.md`

- [src/task1_pipeline/pipeline.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline/pipeline.py)
  - 组织整条任务一流水线
  - 串联加载、抽取、转换、校验、入库、评估、导出

## 6. 默认输出有哪些

默认输出目录为：

```text
outputs/task1/
```

主要输出如下。

### 6.1 数据库

- `outputs/task1/task1_financials.db`
  - 默认 SQLite 数据库文件
  - 包含四张业务表和运行日志表
  - 适合直接在 VS Code / DB Browser / SQLite Viewer 中查看

### 6.2 业务表与日志表 CSV

在当前版本中，四张最终提交业务表会单独输出到：

```text
outputs/task1/final_tables/
```

该目录下的四个 CSV 已严格按照附件 3 的字段数量与字段顺序导出，适合作为任务一最终结果表使用。

- `outputs/task1/artifacts/core_performance_indicators_sheet.csv`
  - 核心业绩指标表的工程中间导出结果
  - 便于调试，不作为最终提交路径优先引用
- `outputs/task1/artifacts/balance_sheet.csv`
  - 资产负债表的工程中间导出结果
- `outputs/task1/artifacts/cash_flow_sheet.csv`
  - 现金流量表的工程中间导出结果
- `outputs/task1/artifacts/income_sheet.csv`
  - 利润表的工程中间导出结果
- `outputs/task1/final_tables/core_performance_indicators_sheet.csv`
  - 核心业绩指标表最终导出结果
  - 已按附件 3 的 20 个字段顺序补齐空列并重排
- `outputs/task1/final_tables/balance_sheet.csv`
  - 资产负债表最终导出结果
  - 已按附件 3 的 21 个字段顺序导出
- `outputs/task1/final_tables/cash_flow_sheet.csv`
  - 现金流量表最终导出结果
  - 已按附件 3 的 18 个字段顺序导出
- `outputs/task1/final_tables/income_sheet.csv`
  - 利润表最终导出结果
  - 已按附件 3 的 21 个字段顺序导出
- `outputs/task1/artifacts/report_file_manifest.csv`
  - 本次实际参与处理的报告清单
  - 含交易所、报告类型、源文件路径等信息
- `outputs/task1/artifacts/extraction_log.csv`
  - 每份报告、每类表的抽取过程日志
  - 可用来排查某张表是通过 `pdfplumber / camelot / 文本兜底` 哪条路径抽出的
- `outputs/task1/artifacts/validation_log.csv`
  - 数据校验日志
  - 记录每条 warning / error 的来源文件、业务键和说明
- `outputs/task1/artifacts/consolidated_records.csv`
  - 四张表合并后的总记录导出
  - 适合做全局抽查、业务键比对和统计分析

### 6.3 评估统计

- `outputs/task1/artifacts/field_coverage.csv`
  - 四张表逐字段覆盖率统计
  - 包含 `record_count / non_null_count / coverage_rate / missing_count`

- `outputs/task1/artifacts/missing_field_stats.csv`
  - 各字段缺失频次统计
  - 适合快速看哪些字段最容易缺

- `outputs/task1/artifacts/missing_reason_stats.csv`
  - 缺失原因汇总表
  - 统计每个字段最主要的缺失原因，如 `likely_extraction_gap`、`likely_not_disclosed_in_source`

- `outputs/task1/artifacts/missing_reason_detail.csv`
  - 每条缺失记录的明细级原因判定
  - 适合做长尾问题排查

- `outputs/task1/artifacts/database_quality_anomalies.csv`
  - 数据库质量复核中的异常值明细
  - 主要记录极端金额、极端比例等会直接影响任务二排序和筛选的问题字段

- `outputs/task1/artifacts/database_quality_field_summary.csv`
  - 数据库质量复核的字段级汇总
  - 汇总高频异常字段和入库前校验规则热点

### 6.4 评估报告

- `outputs/task1/evaluation/summary.json`
  - 本次运行的机器可读摘要
  - 含总记录数、各表记录数、覆盖率、校验结果、主要缺失字段和缺失原因 Top 信息

- `outputs/task1/evaluation/quality_report.md`
  - 面向人工阅读的质检报告
  - 汇总总览、表级覆盖率、高缺失字段和缺失原因判断

- `outputs/task1/evaluation/database_quality_review.md`
  - 面向人工阅读的数据库质量复核报告
  - 汇总入库前校验结果、异常字段热点和重点异常样例

- `outputs/task1/evaluation/manual_audit_template.xlsx`
  - 人工抽样核验模板
  - 可直接用于论文附录或人工质检打分

- `outputs/task1/evaluation/paper_tables.md`
  - 论文实验结果表底稿
  - 已按最终全量结果更新

- `outputs/task1/evaluation/paper_summary.md`
  - 论文实验结果文字稿
  - 已按最终全量结果更新

### 6.5 会计勾稽校验输出

- `outputs/task1/accounting_checks/accounting_check_summary.json`
  - 会计勾稽校验的机器可读摘要
  - 包含规则数、总体通过率、总体失败率以及失败率最高的规则

## 7. 换环境接手建议

如果在新环境继续任务一，推荐按下面顺序恢复：

1. 安装依赖
   - 优先使用项目根目录的 `requirements.txt`
   - 若只想先恢复任务一，可使用 `requirements-task1.txt`
2. 预处理附件 2 清单
   - 运行 `python3 scripts/process_sse_reports.py`
   - 运行 `python3 scripts/process_szse_reports.py`
3. 加载本地环境变量与缓存目录
   - 执行 `source scripts/task1_env.sh`
4. 先跑小样本
   - `python3 run_task1.py --sample-limit 6`
5. 再跑全量
   - `rm -rf outputs/task1`
   - `python3 run_task1.py`
6. 跑完后优先检查：
   - `outputs/task1/evaluation/summary.json`
   - `outputs/task1/evaluation/database_quality_review.md`
   - `outputs/task1/artifacts/validation_log.csv`
   - `outputs/task1/final_tables/*.csv`

如果新环境里任务一结果和任务二暴露的问题不一致，优先怀疑：
- 提取层错列
- 同义字段映射不足
- 可推导字段没有触发
- 极端值过滤阈值不合适

- `outputs/task1/accounting_checks/accounting_check_rule_summary.csv`
  - 每条勾稽规则的汇总统计
  - 包含 `applicable_count / passed_count / failed_count / skipped_count / pass_rate / failure_rate`

- `outputs/task1/accounting_checks/accounting_check_detail.csv`
  - 所有勾稽校验样本的明细结果
  - 每一行对应一条规则在一个业务键上的判定结果

- `outputs/task1/accounting_checks/accounting_check_failed_cases.csv`
  - 仅保留失败样本的明细表
  - 适合直接筛查最需要人工复核的记录

- `outputs/task1/accounting_checks/accounting_check_report.md`
  - 面向人工阅读的勾稽校验报告
  - 汇总总体通过率、分规则通过率以及前若干条失败样例

### 6.6 运行日志

- `outputs/task1/logs/run_meta.json`
  - 记录本次运行的输入清单、输出目录、数据库连接、样本数等信息

## 7. 如何切换到 MySQL

### 7.1 默认行为

如果不传 `--database-url`，程序会默认写入 SQLite：

```bash
python3 run_task1.py
```

此时生成的是：

```text
outputs/task1/task1_financials.db
```

### 7.2 写入 MySQL

如果要写入 MySQL，需要通过 `--database-url` 传入 SQLAlchemy 连接串。例如：

```bash
python3 run_task1.py \
  --database-url "mysql+pymysql://root:password@127.0.0.1:3306/task1_db?charset=utf8mb4"
```

注意：

1. `task1_db` 需要你提前在 MySQL 中创建好
2. 程序会在这个数据库里自动创建表
3. 写入 MySQL 时，不会生成 `.db` 文件
4. 如果仍希望同时保留 SQLite 文件，建议分别跑两次

先创建数据库的示例命令：

```sql
CREATE DATABASE task1_db DEFAULT CHARACTER SET utf8mb4;
```

### 7.3 典型用法

写入 SQLite：

```bash
python3 run_task1.py --sample-limit 30
```

写入 MySQL：

```bash
python3 run_task1.py \
  --sample-limit 30 \
  --database-url "mysql+pymysql://root:password@127.0.0.1:3306/task1_db?charset=utf8mb4"
```

指定新的输出目录并仍使用 SQLite：

```bash
python3 run_task1.py \
  --output-dir outputs/task1_run2 \
  --sample-limit 30
```

## 8. 依赖说明

建议优先安装任务一依赖文件：

- [requirements.txt](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/requirements.txt)

安装后建议先执行：

```bash
source scripts/task1_env.sh
```

## 9. 当前版本边界

当前剩余边界主要集中在少量长尾字段，而不是整体流程失败。

1. 少数公司在 `核心业绩指标表` 中不披露季度环比字段
2. 个别公司在 `合同负债`、`短期借款` 等字段上的版式仍有差异
3. 扫描版 PDF 仍未大规模启用 OCR 主链路
4. 当前全量运行已无 `error`，但仍存在 `17` 条 warning，主要是少量同比/比例异常值
5. 论文最终提交前仍建议结合 `manual_audit_template.xlsx` 做人工抽样复核

## 10. 推荐你现在怎么用

如果你正在准备论文或答辩，建议直接按下面顺序使用：

1. 跑预处理脚本生成处理后目录
2. 运行 `python3 run_task1.py` 完成全量处理
3. 查看 `outputs/task1/evaluation/summary.json` 和 `quality_report.md` 确认最终结果
4. 打开 `outputs/task1/evaluation/manual_audit_template.xlsx` 做人工抽样核验
5. 直接参考 `paper_tables.md` 和 `paper_summary.md` 写任务一实验部分
