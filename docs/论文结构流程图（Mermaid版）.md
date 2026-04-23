# 论文结构流程图（Mermaid 版）

本文档给出四张可直接放入论文的结构流程图。第一张为系统总览图，展示前端问答界面如何承接用户问题，并在结构化财务数据库和向量知识库之上调度 SQL 查询与 RAG 知识增强模块；后三张分别展开任务一、任务二、任务三的具体求解流程。

## 图片文件

已输出的 PNG 图片位于 `docs/figures/`：

![图1 系统总体架构与前端交互流程](figures/图1_系统总体架构与前端交互流程.png)

![图2 任务一财报数据库搭建流程](figures/图2_任务一财报数据库搭建流程.png)

![图3 任务二SQL查询与财务问答流程](figures/图3_任务二SQL查询与财务问答流程.png)

![图4 任务三RAG知识增强与研报问答流程](figures/图4_任务三RAG知识增强与研报问答流程.png)

## 图 1  系统总体架构与前端交互流程

```mermaid
flowchart TB
    FE["前端问答界面"] --> U["用户提问"]
    U --> GATE["任务调度"]

    T1["任务一<br/>数据库搭建"] --> DB[("财务数据库")]
    KB["研报索引<br/>知识库构建"] --> VDB[("向量知识库")]

    GATE -->|结构化问题| T2["任务二<br/>SQL问答"]
    GATE -->|复杂问题| T3["任务三<br/>财务+研报增强"]

    DB --> T2
    DB --> T3
    VDB --> T3

    T2 --> OUT["结构化展示"]
    T3 --> OUT

    classDef main fill:#0d7c66,color:#ffffff,stroke:#075f4d,stroke-width:2px;
    classDef module fill:#e8f5ef,color:#12332d,stroke:#0d7c66,stroke-width:1.5px;
    classDef data fill:#fff3d8,color:#3f2b05,stroke:#b57614,stroke-width:1.5px;
    classDef output fill:#f7fbf9,color:#14221f,stroke:#9bbab0,stroke-width:1.2px;
    class FE,GATE main;
    class T1,T2,T3,KB module;
    class DB,VDB data;
    class U,OUT output;
```

**图示说明：** 系统以 Web 前端作为统一交互入口，用户问题进入任务调度层后，按照问题类型分流至 SQL 问答链路或 RAG 知识增强链路。任务一不由在线调度直接触发，而是作为离线建库模块预先形成结构化财务数据库；研报索引模块与其并行形成向量知识库。任务二主要依赖财务数据库完成结构化数值问答，任务三同时接入财务数据库和向量知识库，实现开放性分析、归因解释和引用复核。

## 图 2  任务一：财报数据库搭建流程

```mermaid
flowchart LR
    A["附件二财报 PDF 库<br/>多公司 · 多年度 · 多格式"] --> B["PDF 预处理<br/>页码定位 · 表格区域识别 · 跨页候选合并"]
    B --> C["表格抽取<br/>资产负债表 · 利润表 · 现金流量表 · 核心指标"]
    C --> D["字段别名映射<br/>公司级字段表达补充 · 同义字段归并"]
    D --> E["数值标准化<br/>单位识别 · 金额换算 · 百分比处理 · EPS 口径约束"]
    E --> F["表间勾稽校验<br/>资产=负债+权益 · 净利润口径 · 现金流合理性"]
    F --> G{"质量判定<br/>完整率 · 极值 · 空缺率 · 勾稽误差"}

    G -->|通过| H[("任务一财务数据库<br/>四张标准化数据表")]
    G -->|未通过| I["回填与修正<br/>直接表值优先 · 公式补全 · 异常收口"]
    I --> F

    H --> J["结果校验脚本<br/>覆盖率统计 · 异常值扫描 · 缺失字段复核"]

    classDef source fill:#f8fbff,color:#17324d,stroke:#6697c7,stroke-width:1.4px;
    classDef process fill:#e8f5ef,color:#12332d,stroke:#0d7c66,stroke-width:1.4px;
    classDef check fill:#fff3d8,color:#3f2b05,stroke:#b57614,stroke-width:1.4px;
    classDef db fill:#0d7c66,color:#ffffff,stroke:#075f4d,stroke-width:2px;
    class A source;
    class B,C,D,E,I,J process;
    class F,G check;
    class H db;
```

**图示说明：** 任务一的核心目标是将非结构化财报 PDF 转换为可计算、可查询、可复核的财务数据库。流程首先通过表格抽取获得原始财务数据，再利用字段别名映射和单位标准化消除不同公司、不同时期披露口径差异。随后通过表内和表间勾稽关系对数据进行质量控制，最终形成覆盖资产负债表、利润表、现金流量表和核心财务指标的结构化数据库。

## 图 3  任务二：SQL 查询与财务问答流程

```mermaid
flowchart TB
    Q["任务二自然语言问题<br/>指标查询 · 排名比较 · 同比环比 · 条件筛选"] --> P["问题解析层<br/>公司识别 · 时间识别 · 指标识别 · 意图分类"]
    P --> C{"澄清门控<br/>信息是否充分？"}

    C -->|需要澄清| CL["生成澄清回答<br/>指出缺失公司、期间或指标"]
    C -->|可以查询| PLAN["查询规划<br/>选择数据表 · 指标映射 · 时间粒度转换"]

    PLAN --> MAP["词汇映射与口径对齐<br/>任务一字段体系 · 财务指标别名 · 年报/季报派生逻辑"]
    MAP --> SQL["安全 SQL 生成<br/>只读查询 · SQLite 兼容 · 禁止危险语句"]
    SQL --> EXE["SQL 执行与异常修复<br/>语法重试 · 空结果诊断 · 字段回退"]
    EXE --> DATA["查询结果表<br/>数值、公司、期间、排序结果"]

    DATA --> CALC["财务派生计算<br/>同比增长率 · 环比变化 · 占比 · 排名"]
    CALC --> CHART{"是否需要图表？"}
    CHART -->|是| FIG["图表规划与渲染<br/>趋势图 · 柱状图 · 对比图"]
    CHART -->|否| ANS["答案生成"]
    FIG --> ANS

    ANS --> CHECK["答案复核<br/>单位一致性 · 数值格式 · 问题覆盖度"]
    CHECK --> OUT["任务二输出<br/>content · image · references"]
    CL --> OUT

    classDef main fill:#0d7c66,color:#ffffff,stroke:#075f4d,stroke-width:2px;
    classDef process fill:#e8f5ef,color:#12332d,stroke:#0d7c66,stroke-width:1.4px;
    classDef decision fill:#fff3d8,color:#3f2b05,stroke:#b57614,stroke-width:1.4px;
    classDef output fill:#f7fbf9,color:#14221f,stroke:#9bbab0,stroke-width:1.2px;
    class Q,OUT output;
    class P,PLAN,MAP,SQL,EXE,DATA,CALC,FIG,ANS,CHECK process;
    class C,CHART decision;
    class CL main;
```

**图示说明：** 任务二面向结构化财务数据问答，重点在于把自然语言问题转化为安全、准确、兼容 SQLite 的 SQL 查询。系统首先识别公司、期间和指标，并在信息不足时触发澄清门控；若条件充分，则进行查询规划和 SQL 生成。查询结果经过同比、环比、排名等派生计算后，由答案生成模块组织为自然语言回答，并根据问题需求生成图表。

## 图 4  任务三：RAG 知识增强与研报问答流程

```mermaid
flowchart TB
    Q["复杂问题"] --> INTENT["意图解析"]

    INTENT --> ROUTE{"链路选择"}
    ROUTE -->|数据库| SQLPLAN["SQL规划"]
    ROUTE -->|研报| RETPLAN["检索规划"]

    SQLPLAN --> SQLDATA["财务证据"]

    RETPLAN --> CHUNK["向量知识库"]
    CHUNK --> HYBRID["混合检索"]
    HYBRID --> RERANK["证据重排"]
    RERANK --> EVID["研报证据"]

    SQLDATA --> FUSE["证据融合"]
    EVID --> FUSE

    FUSE --> VIS{"图表需求"}
    VIS -->|是| CHART["图表生成"]
    VIS -->|否| PROMPT["提示词约束"]
    CHART --> PROMPT
    FUSE --> PROMPT
    PROMPT --> LLM["大模型生成"]

    LLM --> SELF["自检格式化"]
    SELF --> OUT["结构化输出"]

    classDef main fill:#0d7c66,color:#ffffff,stroke:#075f4d,stroke-width:2px;
    classDef process fill:#e8f5ef,color:#12332d,stroke:#0d7c66,stroke-width:1.4px;
    classDef decision fill:#fff3d8,color:#3f2b05,stroke:#b57614,stroke-width:1.4px;
    classDef data fill:#f8fbff,color:#17324d,stroke:#6697c7,stroke-width:1.4px;
    classDef output fill:#f7fbf9,color:#14221f,stroke:#9bbab0,stroke-width:1.2px;
    class Q,OUT output;
    class INTENT,SQLPLAN,RETPLAN,HYBRID,RERANK,FUSE,PROMPT,LLM,CHART,SELF process;
    class ROUTE,VIS decision;
    class SQLDATA,CHUNK,EVID data;
```

**图示说明：** 任务三是在结构化数据库和非结构化研报知识库之上构建的检索增强问答流程。系统根据问题意图动态选择 SQL 查询链路和研报检索链路：前者提供可计算的财务事实，后者提供行业解释、政策背景和图表依据。两类证据经融合后进入分层提示词模板，由大模型生成最终回答，并通过自检模块保证输出字段和引用结构满足提交要求。
