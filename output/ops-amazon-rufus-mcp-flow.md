# ops-amazon-rufus MCP 流程图

## 流程图

```mermaid
%% Rufus MCP 默认获取与一次登录恢复流程。
flowchart TD
    A[用户提供 ASIN、国家站点和可选问题] --> B[解析问题来源]
    B --> B1{问题来源类型}
    B1 -->|多个临时问题| B2[传 questions 列表]
    B1 -->|单个临时问题| B3[传 question 字符串]
    B1 -->|未给问题| B4[传 skills_dir 读取默认题库]

    B2 --> C{宿主是否暴露 amazon_rufus_get}
    B3 --> C
    B4 --> C

    C -->|是| D[调用 amazon_rufus_get]
    C -->|否| Z[改用 opscli amazon-rufus get 兼容入口]

    D --> E[RufusManager.get_backend]
    E --> F[RufusBackendSecretProvider.load 读取本地加密状态]
    F --> G{存在同 ASIN、同国家 streaming seed}
    G -->|是| H[复用本地加密 seed 和 curl_data]
    G -->|否| I[HeadlessRufusCaptureService 打开商品页捕获 /rufus/cl/streaming]

    H --> J[HeadlessRufusClient 按问题逐题请求 Rufus SSE]
    I --> J
    J --> K{请求和解析成功}
    K -->|是| L[AnswerReportWriter 写 output/amazon-rufus 报告]
    L --> M[返回 report_path、题数和 answer_count]
    M --> N[Agent 最终只展示 report_path]
    K -->|否| O[返回 Rufus 稳定错误]
    F -->|状态缺失| O
    I -->|捕获失败| O

    O --> P{错误是否触发登录恢复}
    P -->|否| Q[直接返回原错误]
    P -->|是| R{login_recovery_attempted 是否为 true}
    R -->|是| S[停止恢复，不再打开第二次登录窗口]
    R -->|否| T[设置 login_recovery_attempted=true]
    T --> U[运行 opscli amazon-rufus watch-login ASIN COUNTRY --launch-if-needed]
    U --> V[CLI 打开或连接目标国家站点 Amazon 页面]
    V --> W[用户在 Amazon 页面完成登录]
    W --> X[CLI 自动打开目标 ASIN 商品页并监听 /rufus/cl/streaming]
    X --> Y[加密保存 storage_state、curl_data 和 seed 摘要]
    Y --> D

    Z --> ZA[BrowserAttachService 连接本机 Chrome CDP]
    ZA --> ZB[捕获 seed request]
    ZB --> ZC[RufusReplayService 按问题逐题请求]
    ZC --> L

    subgraph ERRORS[登录恢复触发错误]
        E1[RUFUS_SECRET_NOT_READY]
        E2[RUFUS_HEADLESS_CAPTURE_ERROR]
        E3[RUFUS_HEADLESS_REQUEST_ERROR]
    end

    E1 -.-> P
    E2 -.-> P
    E3 -.-> P

    subgraph SAFE[敏感信息边界]
        S1[不进入 MCP 参数]
        S2[不写入报告]
        S3[不输出到 Agent 回复]
        S4[不提交到 feedback]
    end

    F -. cookie / storage_state / headers / payload 只在服务层内部流转 .-> SAFE
    Y -. 本地加密保存，不展示原文 .-> SAFE
```

## 关键边界

1. 默认入口是 `amazon_rufus_get`，MCP 参数只包含 ASIN、国家、问题来源、`skills_dir` 和超时。
2. `RufusManager.get_backend` 负责读取本地加密状态、复用同 ASIN seed 或走 headless 捕获，再逐题请求 Rufus SSE。
3. 只有 `RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR` 进入登录恢复。
4. 每次 Skill 调用只允许一次登录恢复；恢复后仍失败时直接返回错误，不重复打开登录窗口。
5. 登录恢复使用 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed`，由 CLI 自动监听登录并捕获 streaming seed。
6. cookie、localStorage、`storage_state`、headers、payload、完整请求和 upload payload 都不得进入 MCP 参数、报告、Agent 回复或 feedback。
