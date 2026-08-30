[English](README.md) | [简体中文](README.zh-cn.md)

<!-- ROUND2-PLACEHOLDER: assets/readme/hero.svg
     左右分栏 —— 左：类目行 "AI AGENT · US EQUITIES RESEARCH"、
     Invest+ 字标（复用 logo.svg 的上升折线 + 加号，蓝绿渐变 #3B82F6→#10B981 只用在这里）、
     一句话价值。
     右：只增不改的轨迹 motif —— 每轮追加一行，末行写 "no tool_calls → stop"。
     配色取自 frontend/src/styles/tokens.css。自带 #fafaf9 底，rx 26。 -->

# Invest+ — AI 金融研究助手

用中文或英文问它一支美股。它自己规划研究步骤、拉取实时行情、检索 SEC 财报和新闻，并流式返回一份带来源的答案——用哪个工具、什么时候信息够了可以收尾，全部由它自己判断。

循环、混合检索、跨会话记忆全部手写，没有 Agent 框架。下面每一条效果都是实测的；那些测出来不可信的，也照原样写在这里。

[![License: MIT](https://img.shields.io/badge/license-MIT-35322e.svg)](LICENSE)

<!-- ROUND2-PLACEHOLDER: 其余 badge（CI 状态、在线体验、Python/React），排成一行。
     上面的 MIT badge 已改用项目强调色 #35322e（取自 frontend/src/styles/tokens.css）
     而非 shields 默认蓝，整行保持在中性色板内。 -->

## 在线体验

### [investplus-agent.com](https://investplus-agent.com)

无需注册。可以直接点首页的示例问题，也可以粘贴自己的问题。限流 20 次/分钟，只是挡自动化流量的轻量摩擦，不是真正的访问控制层。

本地跑起来需要 Docker、Elasticsearch、PostgreSQL、两个 API key，外加一次语料索引。[快速开始](#快速开始)给的是最短路径。

<!-- ROUND2-PLACEHOLDER: assets/readme/showcase.png
     线上站的真实截图：思考链 + 最终答案 + 来源三段同框。
     需要你授权采集，仓库里目前一张都没有。 -->

## 实测数据

下面每个数字都来自 [`eval/`](eval/) 里可复跑的评测脚本，驱动真实后端端到端运行——真 agent、真检索、真 Elasticsearch，无 mock。

| 测了什么 | 结果 | 测量条件 | 出处 |
|---|---|---|---|
| 跨语言检索召回 | 纯 BM25 **0/10** → 混合 **10/10** | 10 道中文口语化金融问题，打在本项目纯英文语料上；走的是 `rag_search` 生产环境同一套查询构造代码 | [`eval/recall_validation.py`](eval/recall_validation.py) |
| 工具路由命中率 | 平均 **74.5%** | 17 题 × 3 次采样。稳定命中 10 题、稳定失败 3 题、**翻转 4 题**（同一份代码上时对时错）。单次采样的数字有约 ±24 个百分点的摆动，因此不报 | [`eval/report.md`](eval/report.md) |
| 首个实质判断 | **2.93s** 均值（p50 2.63s / p90 4.86s） | `POST /chat` 到第一条工具调用事件，n=24。衡量响应性要用这个数 | [`eval/report.md`](eval/report.md) |
| 全程响应延迟 | **32.6s** 均值（p50 31.9s / p90 55.0s） | 32 次真实流式请求，从开始到流式回答结束 | [`eval/results.json`](eval/results.json) |
| RAG 回答准确率 | **13/15** | 事实型问答对，对照已索引语料核实。按问出去的全部 15 题计。其中 1 题（`rag-11`）被判定测试设计有缺陷——它的 ground truth 是时间快照，问题问的却是相对当前日期的浮动概念——剔除后为 13/14；这里报的是保守口径 | [`eval/report.md`](eval/report.md) |
| 边界输入鲁棒性 | **5/5** | 空输入、超长输入、无效 ticker、跑题问题、不存在的会话 | [`eval/report.md`](eval/report.md) |
| 循环重构前 → 后 | 工具调用 **77 → 34**，平均耗时 **108.7s → 75.3s** | 同一批 5 道题，各跑一次，两次都压进了补充轮（补充调用分别为 23 次和 19 次）。严格重复与近似重复在**两次里都是 0**——见[重构那一节](#1-真正的-agent-循环不是写死的流水线) | [`repeat_probe_master-original.md`](eval/repeat_probe_master-original.md)、[`repeat_probe_increment-2.md`](eval/repeat_probe_increment-2.md) |

对着运行中的后端自己复跑：

```bash
python eval/run_eval.py --routing-samples 3
```

### 延迟到底花在哪

上面两行延迟说的是"要多久"，这一节说的是"那该动哪里"。同样这 32 次请求里，思考内容均值 **1810 字符**，可见回答均值 **486 字符**，相差 3.7 倍。而可见回答也不是时间的去处：全程 32.6s 里，回答开始流式输出之后只占 **11%**。

两个长度对延迟的贡献并不对等。思考长度与总延迟的相关系数是 **r = 0.90**，可见回答长度只有 **r = 0.68**。所以"把回答写短一点"这个最直觉的动作几乎买不到什么，真正的杠杆是回答调用上的 `enable_thinking`。

两个相关系数都由 [`eval/results.json`](eval/results.json) 里逐条的 `thinking_chars`、`answer`、`total_latency` 字段算出，可以重算复核，不必采信。

### 本项目不主张的数字

有三个指标建好、跑过，然后被判定作废。它们记录在这里而不是被悄悄丢掉，因为每一个作废前都是往好看的方向偏的。

- **"首 token 延迟"。**自 `448b831` 起，第一个 SSE 事件是后端在任何 LLM 调用**之前**就发出的受理确认，测出来恒为 0.00s。它只能证明连接已建立，对模型、检索、工具都不说明任何事情。要谈响应性请引用"首个实质判断"。
- **单次采样的路由准确率。**17 题里有 4 题在同一份代码上跑一次对一次错，给任何单次采样的数字带来约 **±24 个百分点**的摆动。任何前后对照只要差异小于这个幅度就读不出结论，所以只报多次采样的平均值。
- **SOP 注入的覆盖提升。**两把尺子都是坏的。旧的那把数生成子问题里的关键词，但 `finance_query` 并不解析具体指标——`"AAPL PE ratio"` 和 `"AAPL fundamentals"` 返回逐字节相同的结果，所以它奖励的是啰嗦而不是信息量。改用工具实际返回的内容重新打分，提升从 +52.8pp 掉到 +11.1pp——但新尺子同样会饱和，因为基本面卡片恒定包含 5 个估值概念里的 2 个。重新设计评分维度是尚未完成的工作。

**语料真实性声明：**`data/` 是项目自带的测试语料，部分由 AI 生成、日期为未来虚构日期。RAG 准确率衡量的是回答对已索引语料的忠实度，不代表对真实世界财务数据的验证。

## 它是什么

一个跑在三个工具和一个知识库之上的研究 Agent。`rag_search` 对 SEC 财报（10-K/10-Q/8-K）、新闻和科普参考文章做混合检索；`finance_query` 通过 yfinance 取实时行情、基本面和新闻；`web_search` 覆盖知识库没有的全市场动态。还有第四个工具 `load_sop`，它加载研究 playbook，不取外部数据。

它自动识别输入是中文还是英文并用同种语言回答，通过 SSE 把推理链和答案一起流式推出，跨会话记住你，并接受你自己的 `.txt` / `.md` / `.pdf` 文件作为补充上下文。每个回答末尾的免责声明由代码在生成之后追加——不是靠提示词要求，所以模型漏不掉。

## 它有什么不一样

### 1. 真正的 Agent 循环，不是写死的流水线

<!-- ROUND2-PLACEHOLDER: assets/readme/agent-loop.svg
     从 diagrams/invest-plus-agent-loop.workflow.json 重新渲染 ——
     改 meta.locale 与各 label 字段做英文化、套项目配色、导出静态图。
     不要从已构建的 HTML 里抠 SVG。 -->

```text
用户问题
      ↓
  静态前缀            ── system 提示词 + 工具定义 + SOP 元数据目录；
      ↓                   跨请求逐字节稳定，因此可被缓存
  决策操作            ── 循环：一次 LLM 调用同时回答"还要不要继续取数"和
      ↓  （有界循环）      "调哪个工具、传什么参数"，以原生 tool_calls 输出
  process_actions()   ── 调用 rag_search / finance_query / web_search / load_sop；
      ↓                   工具报错会暴露给 LLM，不被吞掉
      ↓                 结果作为 tool 角色消息追加进轨迹，
      ↓                   与各自的 tool_call_id 配对；这个列表只增不改
  final_answer()      ── 换更强的模型单独调一次；经 SSE 流式输出
      ↓
  前端渲染思考链 + 最终答案
```

每一次继续/停止/重试的决策都来自模型自己输出的原生 `tool_calls`，不是硬编码分支——某一轮没有工具调用**本身就是**停止信号。循环只在三种条件下退出：没有新的工具调用、触达轮次上限、或某次调用报错。安全上限是 6 轮决策（`MAX_DECISION_ROUNDS`，`agent.py:894`），给失控循环兜底——即 1 轮规划加最多 5 轮补充。触达上限而停止与模型主动发出停止信号，在日志里分开记录，两者不会被混淆；当上限先触发时，最终答案会明确声明信息可能不完整，而不是把部分结果当作详尽结果呈现。工具失败会追加进模型自己能读到的轨迹，所以它能重试、降级，或者把缺口标出来。

`final_answer()` 刻意不挂在轨迹上——它用一次额外往返、外加一个与循环不共享缓存的模型，换来更高质量的答案。

**工具选择规则：**

| 问题形态 | 工具 |
|---|---|
| 实时行情 / 市值 / 市盈率 / 基本面 / 新闻标题 | `finance_query` |
| 财报内容 / 风险因素 / 新闻分析 / 概念解释 | `rag_search` |
| 知识库没覆盖的最新全市场动态 | `web_search` |
| 与金融无关的话题 | 拒绝回答 |

<details>
<summary><b>这个形态是重构的结果。第一版错在哪。</b></summary>

第一版把工具说明写在提示词正文里，让模型吐 JSON 文本由后端解析，并且每一轮都把攒下来的工具结果重新序列化成一条新的 user 消息。

最后那一点正是现在这套设计要避开的失效模式：模型看到的从来不是自己的调用历史，而是被应用层重新格式化过的文字，于是它会重新发起已经调过的调用。当时加了两层去重来压住这个现象，轨迹做实之后两层都被删掉了。

"起作用的是轨迹而不是去重代码"这条论断是可证伪的，于是就用删掉去重、再探测重复会不会回来的方式验证了它。重复没有回来：旧形态 23 次补充调用、新形态 19 次补充调用，严格重复与近似重复都是 0。真正变化的是量和时间——同样五道题、各跑一次，工具调用总数 77 → 34，平均耗时 108.7s → 75.3s。

在证明这次运行**有能力**测到重复之前，上面这些都不算数。一批题里如果没有任何请求进入过补充轮，就不可能产生重复调用，那么在它上面测出的"零重复"不是弱证据，而是没有证据——它支持和反驳这条论断的力度完全相等。早先确实有过这样一次运行：5 个请求里 0 个进入补充轮，它的判定被记为**未测到**，而不是**未复现**。上面引用的两次运行都先过了这一关，都是 5/5。

样本量仍然只有五道题，而且这是模型行为而非确定性属性，所以即便是通过的那次，判定也只写成"在本样本内未复现"，不写成已证明。

</details>

### 2. 换一种语言问也召得回来的混合检索

`rag_search` 在同一个 Elasticsearch 索引上组合两路信号——原生 ES 8.11 `knn` + `query`，手写实现，不依赖 RAGFlow：

- **BM25**（`content_ltks` 全文匹配）—— 精确的关键词命中。
- **向量 kNN**（`q_1024_vec`，text-embedding-v3，余弦）—— 语义与跨语言命中。

两路的分数相加，向量那一路做了 boost 以平衡量纲；如果查询 embedding 失败，会优雅降级为纯 BM25。合并后的候选交给 qwen3-vl-rerank 精排，再按用户最近上传做 boost，最终截断为 top 5。

这就是上表里 0/10 → 10/10 那一行背后的机制：面对纯英文语料，中文口语化问题对关键词检索是完全不可见的，加上向量那一路之后则全部可召回。

### 3. 真正进到答案里的记忆，不只是进到规划里

进入决策循环之前，`final_answer()` 会召回用户画像（`recall_user_profile`，`service/memory/profile.py`），以及问题里提到的 ticker 对应的、尚未过期的调研结论。ticker 提取用的是一个能容忍 CJK 的正则（`_extract_tickers_loose`，`agent.py:416`），因为 `_TICKER_RE` 的 `\b` 词边界会漏掉贴着中文的 ticker——例如 `AAPL的股价`。

两者都会织进规划提示词，好让 agent 跳过冗余的取数；而召回的结论**还会**同时拼进最终答案的提示词——所以一条从上次会话里记下来的事实，能真的出现在这一轮的答案里，而不只是影响调了哪些工具。召回内容被 `<untrusted_context>` 包裹，并附一条"若与实时数据冲突，以实时数据为准"的明确指令，与工具结果用的是同一套约定。

结论带分级 TTL —— 基本面和财报类事实约 90 天，新闻约 30 天。实时行情从不作为记忆持久化，每次都实时召回。

<details>
<summary><b>事实是怎么写进去的，以及抽取 LLM 和数据库之间隔着什么</b></summary>

每 5 轮对话，一个由 `BackgroundTasks` 调度的任务（`service/memory/extraction.py`）读取最近的对话，请 LLM 抽取结构化事实——更新后的偏好、带时间戳的结论。它不增加请求延迟。

实时行情数据在进入校验之前就被代码丢弃了，它没有理由被当作长期"记忆"缓存。活下来的内容要经过确定性的 schema 校验——枚举、ticker 与指标名正则、长度上限——才会落库。因此，一次针对抽取 LLM 的成功提示注入可以产出令人困惑的**内容**，但写不出越界的字段值，也逃不出被沙箱化的提示词字符串。

</details>

### 4. 由模型主动取用的技能库，而不是后端强行推送的

四份研究 playbook 以纯 Markdown 存放在 `service/agent/skills/` 下——`valuation.md`、`financial_statement.md`、`industry_comparison.md`、`risk_scan.md`，各带 YAML frontmatter 和一份指标清单。常驻决策 system 提示词的只有它们的 `name` + `description` 组成的元数据目录；正文只有在模型调用 `load_sop` 时才进入上下文。这个拆分的实测成本是：常驻 813 字符，对应正文 3082 字符，占 26%。

它替代的是一次在每轮规划前无条件执行的 `classify_skill()` 往返。省下来的不是需要 playbook 的那些问题——那些是打平的，一次分类调用变成一次 `load_sop` 调用——而是不需要 playbook 的问题从此完全不用付这笔钱。

如实地说，这次切换损失了一些路由召回：正例从 19/19 降到 16/19，假正例保持 0/16，而这三个里只有一个是干净的回退——一个是数据集标注自相矛盾，另一个是打分口径不匹配，因为旧调用把输出硬上限设成了两个技能，而 `load_sop` 没有这个上限。耗时则悬而未决：这条路径结构上少了一整次 LLM 往返，但几次测量在采样噪声之内互相矛盾，所以两个方向的结论都不作主张。

SOP 正文刻意永远不进入记忆通道——它们是给模型的指令，不是关于世界的事实，放进去等于把用户自己的方法论清单当作被引用的参考资料再喂回给他。有一个测试把这条钉死了。

## 快速开始

**前置条件：** Docker Desktop（若在 WSL2 上需开启 WSL 集成）、Python 3.11+、Node.js 18+、一个 DashScope API key（阿里云）、一个 Serper API key。

**1. 环境变量。** 复制 `.env.example` 为 `.env` 并填入你的 key：

```env
DASHSCOPE_API_KEY=your_dashscope_key
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
SERPER_API_KEY=your_serper_key
ES_URL=http://localhost:1200
ELASTIC_PASSWORD=your_elastic_password
TIMEZONE=Asia/Shanghai
MEM_LIMIT=4294967296
PG_MEM_LIMIT=1073741824
POSTGRES_PASSWORD=your_postgres_password
DATABASE_URL=postgresql://postgres:your_postgres_password@localhost:5432/investplus
```

**2. 基础设施与依赖。**

```bash
docker compose up -d
pip install -r requirements.txt
```

**3. 构建知识库。** 抓取语料并索引进 Elasticsearch 的 `finance_kb` 索引。一次性操作，也是最慢的一步。

```bash
python scripts/fetch_filings.py       # SEC EDGAR 10-K/10-Q/8-K  -> data/filings/
python scripts/fetch_news.py          # 各 ticker 近期新闻        -> data/news/
python scripts/fetch_educational.py   # 科普参考文章              -> data/educational/
python scripts/index_finance.py       # 切块 + embedding + 索引三者
```

**4. 后端。** 注意工作目录——导入是扁平的，所以必须从 `backend/app` 起，不是 `backend/`。

```bash
cd backend/app
uvicorn app_main:app --reload --port 8000
```

**5. 前端。**

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

打开 [http://localhost:5181](http://localhost:5181)。

## 技术栈

| 层 | 技术 | 职责 |
|---|---|---|
| LLM | Qwen —— qwen3.7-max（最终回答）、qwen-plus（决策操作），经 `openai` SDK 打到 DashScope 的 OpenAI 兼容端点 | 推理 + 工具决策 |
| Agent | 手写循环：静态前缀 + 只增不改的轨迹 + 原生工具调用（无 LangChain） | 工具编排 + 自我纠错 |
| 知识库 | Elasticsearch `finance_kb`（财报 + 新闻 + 科普 + 用户上传）；向量用 text-embedding-v3，精排用 qwen3-vl-rerank（原生 `dashscope` SDK） | 混合检索（BM25 + 向量）+ 精排 |
| 实时数据 | yfinance（`service/finance/finance_tool.py`） | 行情 / 基本面 / 新闻 |
| 文档解析 | DeepDoc（版式 / table-transformer / OCR，onnxruntime） | PDF 财报上传 → 带表格结构的分块 |
| 网络搜索 | Serper API | 最新市场动态 / 兜底 |
| 后端 | FastAPI + PostgreSQL | API、SSE、会话与消息；`user_profiles` / `conclusion_memory` |
| 记忆与技能 | `service/memory/{profile,conclusion,extraction}.py`、`service/agent/skills/*.md` | 跨会话召回、抽取流水线、SOP 驱动的规划 |
| 前端 | React + TypeScript + Vite + Ant Design + Valtio | 聊天 UI、流式渲染、文档管理 |
| 基础设施 | Docker Compose（开发环境 ES + PG；生产环境全栈 + nginx 网关 + Let's Encrypt） | 本地依赖 / 生产托管 |
| CI/CD | GitHub Actions + GHCR | 每次 push 构建并推送镜像；`master` 上 SSH 部署 |

## 生产部署

<!-- ROUND2-PLACEHOLDER: assets/readme/deployment.svg
     从 diagrams/invest-plus-deployment.architecture.json 重新渲染 ——
     英文化 label、套项目配色、导出静态图。不适合放首屏。 -->

[在线体验](#在线体验)就跑在这个仓库上，方式是在开发用的 Compose 之上再叠一层：

- **`docker-compose.prod.yml`** —— 增加 `backend` / `frontend` / `gateway` 三个服务，为每个服务钉死 `mem_limit`（依据真实负载下实测的容器内存标定，不是拍的），并去掉 `es01` / `pg` 仅供开发用的宿主端口映射。
- **`gateway/`** —— 唯一的公网入口是一个 nginx 容器：TLS（Let's Encrypt 经 `certbot`，两阶段引导以打破证书与 nginx 启动顺序的先有鸡还是先有蛋）、`/ai-search/*` 反向代理到后端并放行 SSE（关闭缓冲）、以及请求限流。
- **`.github/workflows/deploy.yml`** —— push 到 `master` 时：构建 `backend` / `frontend` / `gateway` 三个镜像并推到 GHCR，然后 SSH 进服务器执行 `pull` + `up -d`。部署用的 SSH key 只会执行这两条命令；业务密钥（`.env`）由人工一次性放到服务器上，从不经过 CI 传输。

这不是一套通用的"到哪都能部署"模板。compose 文件和网关配置是针对本项目特定的服务布局写的，`mem_limit` 的取值也是对着某一个特定规格的虚拟机标定的。请把它们当作一个做完了的样例，而不是可以直接套用的现成件。

<!-- ROUND2-PLACEHOLDER: assets/readme/chat-sequence.svg（可选，折叠放置）
     来自 diagrams/invest-plus-chat-sequence.json。信息密度高 —— 6 个参与者、
     5 个耗时区段。嵌入前须在 900px / 360px 两档验证可读性；
     不达标就不要放，别靠缩小标签硬塞。 -->

## 已知局限

### 路由与检索

- **三个稳定的路由失败** —— 三次采样全错的那几个，所以是真实缺陷而非采样噪声。
- **召回路径上 ticker 与缩写的歧义** —— 容忍 CJK 的那个提取器无法区分金融缩写和同名的真实 ticker（`AI` 既是"人工智能"也是 C3.ai）。

<details>
<summary>两条的细节</summary>

`route-05`（"什么是自由现金流？"）给一个知识库本就能回答的概念问题多加了一次不必要的 `web_search`。`route-11`（"今天有什么重要的全球财经新闻？"）一个工具都没调。`route-17` 把一个复合问题里属于新闻的那一半发给了 `rag_search` 而不是 `web_search`。

有一次修复尝试被回退了：按时间词（"最近"、"最新"、"今天"）来路由，修好了 `route-11` 和 `route-17`，却改坏了一道问"最近的 8-K"的对照题——那是归档文件，不是实时新闻。边界必须按答案存放在哪里来划——归档文档给 `rag_search`，真实世界的实时状态给 `web_search`——而不是按问题听起来是不是很"新"。

关于缩写撞车：宽松的那个提取器只用于结论召回，`finance_tool()` 并不用它，后者对已经拆解过的子问题用的是更严格的一个。最坏情况是一条不相关的旧结论作为背景浮现出来，而召回提示词本来就把这类内容当作可能已过期来处理。

</details>

### 记忆

- **抽取按轮次触发，不按会话结束触发** —— 请求-响应架构里没有可靠的"会话已结束"信号，所以它每 5 轮触发一次。一段在窗口内第 *N*-1 轮结束的对话，尾巴永远不会被抽取。
- **`BackgroundTasks` 抽取不做持久化也不重试** —— 若进程在调度与执行之间重启，那一批事实就丢了。窗口之间不重叠，所以影响边界是"有些记忆没被记下来"，不是数据损坏。
- **单用户假设** —— `chat_rt.py` 里硬编码的 `USER_ID` 用于画像召回，而抽取是从会话自己的行里推导写入用户。两者今天恰好一致，但在支持真正的多用户之前必须先对齐。

### 数据接入

- **PDF 解析覆盖的是上传件，不是批量语料** —— DeepDoc 流水线接的是 `/upload_files` 的用户上传，而 `scripts/index_finance.py` 走的是 SEC 财报原生的 HTML（iXBRL），因为 EDGAR 并不以 PDF 形式提供现代财报。详见该模块的 docstring。

### 前端

- **聊天界面只支持桌面** —— `components/page-layout` 有一个硬性的 `min-width: 600px` 外加固定 `408px` 的侧栏，而 `layout/base` 给每个路由都套了固定 `100px` 的侧边栏。没有任何 `@media` 断点覆盖聊天页；在手机视口下它是溢出而不是重排。落地页本身的响应式还算可以。
- **没有会话历史界面** —— `session_id` 只存在于 URL（`/chat/:id`），不写 `localStorage`。服务端有 `DELETE /sessions` 接口，但前端没有任何地方调它。每次访问都是新会话，旧会话在 Postgres 里无限期留存，没有 TTL。

## 路线图

当前 MVP 覆盖的是单支股票的行情与市场分析（AAPL / MSFT / GOOGL）。从架构上讲，这是一个更宽的投研 copilot 的地基——组合层面的推理、多资产对比——复用同一套工具与检索层。

## 项目结构

<details>
<summary><b>完整目录树，含逐文件注释</b></summary>

```
InvestPlus/
├── backend/
│   ├── Dockerfile                   # 生产镜像：依赖 → tiktoken/nltk 预烤 → 应用代码（这个层序让只改代码时能命中缓存）
│   ├── app/
│   │   ├── app_main.py              # FastAPI 入口
│   │   ├── router/
│   │   │   ├── chat_rt.py           # /chat SSE、/upload_files (.txt/.md/.pdf)、/get_files、/delete_file
│   │   │   └── history_rt.py        # /sessions、/messages
│   │   ├── service/
│   │   │   ├── agent/
│   │   │   │   ├── agent.py         # Agent 循环（轨迹上的决策操作）+ 记忆/技能的召回与注入
│   │   │   │   └── skills/          # SOP playbook：valuation/financial_statement/industry_comparison/risk_scan.md
│   │   │   ├── memory/
│   │   │   │   ├── profile.py       # recall_user_profile / upsert_user_profile
│   │   │   │   ├── conclusion.py    # recall_conclusion_facts / upsert_conclusion_fact（分级 TTL）
│   │   │   │   └── extraction.py    # extract_memory() —— 每 5 轮触发的 LLM 抽取流水线
│   │   │   ├── finance/             # finance_tool.py —— yfinance 实时行情/基本面/新闻
│   │   │   ├── web_search/          # Serper 网络搜索工具
│   │   │   └── core/
│   │   │       ├── file_parse.py    # .txt/.md 切块器 + .pdf DeepDoc 流水线 -> ES 索引
│   │   │       ├── deepdoc/         # PDF 解析器（版式/表格/OCR）
│   │   │       └── rag/             # 分词/NLP 工具 + res/deepdoc 模型权重
│   │   ├── models/memory.py         # SQLAlchemy 模型：UserProfile、ConclusionMemory
│   │   ├── schemas/chat.py
│   │   └── utils/database.py
│   └── tests/
│       ├── test_agent_loop.py       # 循环机制单测（should_continue、错误传播）+ 合并步骤测试
│       ├── test_chat_router.py      # /chat SSE + 相关路由端点
│       ├── test_history_router.py   # /sessions、/messages
│       ├── test_finance_tool.py     # yfinance 封装、失败降级、ticker 缓存
│       ├── test_file_parse.py       # .txt/.md/.pdf 切块 + ES 索引
│       ├── test_pdf_parser.py       # DeepDoc PDF 解析器
│       ├── test_es_client.py        # Elasticsearch 客户端单例/配置
│       ├── test_knowledgebase_operations.py
│       ├── test_index_finance.py    # 批量语料索引器
│       ├── test_e2e_finance.py      # 打到运行中后端的端到端冒烟测试
│       ├── test_memory_layer.py     # 画像/结论读写 + 抽取校验
│       ├── test_memory_recall.py    # 容忍 CJK 的 ticker 提取 + 召回接线
│       ├── test_memory_scheduling.py # BackgroundTasks 触发的判别性测试
│       └── test_skill_sop_and_disclaimer.py
├── eval/                            # Agent/RAG 量化评测脚本
├── frontend/
│   ├── Dockerfile                   # 多阶段：npm 构建 -> 静态资源由 nginx 托管
│   └── src/
│       ├── i18n.tsx                 # 双语文案（zh/en）
│       ├── styles/tokens.css        # 设计 token —— 唯一真源，在 tokens.ts 有镜像
│       ├── components/
│       │   ├── header-bar/          # 顶栏，含中/EN 切换
│       │   └── sender/              # 输入框 + 附件
│       └── pages/
│           ├── chat/                # 聊天页，SSE 流式
│           └── repository/          # 文档管理
├── gateway/                         # 生产入口：nginx TLS/反向代理/限流
│   ├── nginx.conf                   # 生产配置（TLS、真实域名）
│   └── nginx.local.conf             # 本地全栈等价配置（纯 HTTP，无 certbot）
├── diagrams/                        # 架构 / 流程 / 时序图的源文件与渲染产物
├── .github/workflows/deploy.yml     # CI：每次 push 构建 3 个镜像；master 上还会推 GHCR + SSH 部署
├── scripts/                         # 语料抓取/索引脚本
├── data/                            # 抓取到的金融语料，索引进 `finance_kb`
├── docker-compose.yml               # ES + PostgreSQL（共享基座）
├── docker-compose.local.yml         # + backend/frontend/gateway，本地全栈开发（纯 HTTP）
├── docker-compose.prod.yml          # + backend/frontend/gateway/certbot，生产（TLS、mem_limit 钉死）
└── .env                             # API key 与配置
```

</details>

## 许可 / 版权说明

以 [MIT License](LICENSE) 发布 —— Copyright (c) 2026 Thomas Lee。它覆盖原创的应用与 Agent 代码，包括混合检索（`agent.py` 里的 `rag_search`）——那部分是直接基于原生 Elasticsearch 手写的，不依赖 RAGFlow。

有一个目录不在它的覆盖范围内：

PDF 解析流水线（`service/core/deepdoc`、`service/core/rag`）移植自 [RAGFlow](https://github.com/infiniflow/ragflow)，仍然适用 Apache License 2.0，Copyright The InfiniFlow Authors。这两棵树里每个带代码的文件都保留了原始许可头——两个空的 `__init__.py` 包标记文件除外——完整的许可副本就放在它们旁边：[`backend/app/service/core/LICENSE-APACHE-2.0`](backend/app/service/core/LICENSE-APACHE-2.0)。这两棵树下随附的 `.onnx` 模型权重不在本说明覆盖范围内，其许可以上游 RAGFlow 为准，本仓库未做核实。

财报来自 [SEC EDGAR](https://www.sec.gov/edgar)，行情数据来自 [yfinance](https://github.com/ranaroussi/yfinance)，LLM 来自阿里云 DashScope。
