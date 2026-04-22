# 任务一使用说明

## 1. 模块定位

任务一负责从附件 2 财务报告 PDF 中抽取四张目标表，完成字段映射、单位统一、质量校验、数据库入库与评估输出。

主入口：

- [run_task1.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task1.py)

当前任务一已经回归单一主线结构，不再保留 `task1_test` 等独立测试分支。当前正式实现统一位于：

- [src/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline)

它不仅服务任务二，也直接服务任务三的 SQL 查询层，因此任务一的数据质量会同时影响后两项任务。

当前 `outputs/task1` 下的最新全量结果，已作为任务一正式版结果使用。

---

## 2. 当前已完成能力

当前版本已经覆盖：

1. 财报目录预处理
2. PDF 文本与表格抽取
3. 字段映射与单位统一
4. 跨表补值与派生指标
5. 字段来源约束
6. 候选表评分与筛选
7. 异常值清洗
8. SQLite / MySQL 入库
9. 数据库质量复核
10. 会计勾稽校验
11. 论文材料与评估输出

当前主线版本的全量结果如下：

- 有效处理报告数：`1235`
- 主记录总数：`3293`
- 四张业务表记录数：
  - `balance_sheet`: `823`
  - `cash_flow_sheet`: `823`
  - `core_performance_indicators_sheet`: `824`
  - `income_sheet`: `823`
- 平均字段覆盖率：
  - `balance_sheet`: `0.9978`
  - `cash_flow_sheet`: `0.9952`
  - `core_performance_indicators_sheet`: `0.9558`
  - `income_sheet`: `0.9983`
- 入库前 warning：
  - `cash_flow_sheet|warning = 163`
  - `core_performance_indicators_sheet|warning = 5`
- 入库后会计勾稽脚本总体通过率：`97.97%`

当前正式版结果文件主要位于：

- [outputs/task1/evaluation/summary.json](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task1/evaluation/summary.json)
- [outputs/task1/evaluation/quality_report.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task1/evaluation/quality_report.md)
- [outputs/task1/evaluation/database_quality_review.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task1/evaluation/database_quality_review.md)
- [outputs/task1/accounting_checks/accounting_check_report.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task1/accounting_checks/accounting_check_report.md)
- [outputs/task1/final_tables](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task1/final_tables)

综合覆盖率、异常值复核、按行空缺分布与勾稽脚本结果判断，这一版未再发现系统性错页、错列或单位放大问题，因此可以作为任务一最终版本。

---

## 3. 当前重点

当前任务一后续重点主要有：

1. 继续收口核心指标表口径问题
   - `net_profit_excl_non_recurring_yoy`
   - 少量 `qoq` 长尾样本
   - 个别 `EPS / 每股类` 残余冲突
2. 继续减少现金流尾部勾稽 warning
3. 继续补充长尾公司别名与旧版披露写法
4. 保持主线结果与论文、校验脚本、导出结构同步
5. 任务二 / 任务三一旦出现离谱结果，优先回查任务一数据层

如果后续不再继续调任务一本身，那么这里的“重点”更适合理解为后续维护方向，而不是阻止当前版本定稿的问题。

---

## 4. 核心技术路线

任务一当前采用“**预处理 - 抽取 - 转换 - 融合 - 校验 - 入库 - 评估**”闭环框架。

### 4.1 抽取层

- `PyMuPDF`
- `pdfplumber`
- `camelot`
- 文本兜底与续表重建

### 4.2 标准化层

- 中文别名映射
- 单位统一
- 负数 / 百分比 / 百分点归一

### 4.3 融合层

- 候选表评分
- 跨表补值
- 派生指标计算
- 直读优先、异常再回填
- 同公司同年份累计披露值还原单季度后再计算 `qoq`
- `Q3` 双口径列识别与累计值优先

### 4.4 质量控制层

- 必填字段检查
- 主键重复检查
- 极端金额 / 极端比例过滤
- 毛利率 / 净利率 / ROE / 现金流占比一致性预校验
- `EPS` / 每股净资产 / 每股经营现金流一致性校验
- 季度环比 / 扣非同比一致性校验
- 数据库级会计勾稽校验

---

## 5. 常用命令

### 5.1 主流程

```bash
python3 run_task1.py
```

### 5.2 抽样运行

```bash
python3 run_task1.py --sample-limit 10
```

### 5.3 只从已有数据库重导最终表

```bash
python3 scripts/export_task1_final_tables.py
```

### 5.4 会计勾稽校验

```bash
python3 scripts/check_task1_accounting_consistency.py
```

该脚本当前会输出：

- 规则级通过率汇总
- 失败样本明细
- Markdown 版勾稽报告

当前脚本共包含 `16` 条规则，覆盖：

- 资产负债表恒等式与资产负债率
- 现金流勾稽与三类现金流占比
- 毛利率、净利率、ROE、每股类字段一致性
- 营收环比、净利环比、扣非同比一致性
- `EPS` 与净利润符号一致性

---

## 6. 关键文件

- 主入口：
  - [run_task1.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task1.py)
- CLI：
  - [src/task1_pipeline/cli.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/cli.py)
- Pipeline 组织：
  - [src/task1_pipeline/pipeline.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/pipeline.py)
- 元数据标准化：
  - [src/task1_pipeline/metadata.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/metadata.py)
- 字段来源约束：
  - [src/task1_pipeline/field_rules.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/field_rules.py)
- 字段映射：
  - [src/task1_pipeline/mappings.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/mappings.py)
- 提取层：
  - [src/task1_pipeline/extractor.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/extractor.py)
- 单位与数值标准化：
  - [src/task1_pipeline/normalizers.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/normalizers.py)
- 转换层：
  - [src/task1_pipeline/transform.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/transform.py)
- 入库前校验：
  - [src/task1_pipeline/validator.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/validator.py)
- 评估与质量复核：
  - [src/task1_pipeline/evaluate.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/evaluate.py)
  - [src/task1_pipeline/quality_review.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline/quality_review.py)
- 勾稽脚本：
  - [scripts/check_task1_accounting_consistency.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/scripts/check_task1_accounting_consistency.py)

---

## 7. 当前边界

当前仍需重点关注：

- 现金流表尾部勾稽仍有长尾 warning
- 核心指标表中少量同比/环比字段仍存在口径差异
- 少量公司在季度报告中存在“本报告期 / 年初至报告期末”混排问题
- 个别长尾公司旧版字段表达仍需继续补 alias

整体判断：

**任务一主线已经可作为任务二、任务三的数据底座使用；当前 `outputs/task1` 这版结果可视为任务一最终版本。**
