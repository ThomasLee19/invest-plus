[English](README.md) | [简体中文](README.zh-cn.md)

# Invest+ — AI 金融研究助手

Invest+ 是一个面向美股的自主研究 Agent。用中文或英文问它一支股票的情况，它会自己规划研究步骤、拉取实时行情、检索 SEC 财报和新闻，并流式返回一份带引用来源的答案——用什么工具、什么时候信息够了可以收尾，全部由它自己判断。

## 在线体验

**[https://investplus-agent.com](https://investplus-agent.com)**

部署在单一 Docker Compose 技术栈上（Elasticsearch + PostgreSQL + backend + frontend，前面挂一个带 Let's Encrypt TLS 的 nginx 网关），托管在非中国大陆节点，每次 push 到 `master` 都会经 GitHub Actions CI/CD 自动部署。限流（20次/分钟）只是挡随手访问/自动化爬虫的轻量摩擦，不是真正的访问控制层——详见[生产部署](#生产部署)。

## 功能特性

- **自主 Agent 流水线** — Plan → Act → Reflect → Answer。Agent 自己决定调用哪些工具、把问题拆成子问题，并持续反思/补充信息直到自己判断答案完整（设了安全上限防止无限循环——如果在LLM发出"完成"信号前先触达上限，最终答案会明确说明信息可能不完整，而不是把部分结果当作详尽结果呈现）。没有写死的决策树——每一次"继续/停止/重试"的判断都来自LLM自己的判断。
- **三个研究工具**：
  - `rag_search` — 对 SEC 财报（10-K/10-Q/8-K）、新闻和科普参考文章知识库做混合检索（BM25 + 向量）
  - `finance_query` — 通过 yfinance 获取实时行情（报价、基本面、近期新闻）
  - `web_search` — 通用网络搜索，补充知识库里没有的最新市场动态
- **流式、可见的推理过程** — SSE 流式传输，Agent 的实时思考/推理链跟最终答案一起展示，不只是给结果。
- **中英双语** — 自动识别输入是中文还是英文并用同种语言回复；界面自带中/EN切换。
- **多轮对话** — 按session区分的聊天历史。
- **文件上传** — 上传自己的 `.txt`/`.md`/`.pdf` 文件（PDF用带表格识别能力的版式/OCR流水线解析）；在Docs页面管理。
- **真正能用的跨语言检索** — 混合BM25+向量检索能召回纯关键词检索完全漏掉的口语化查询结果（详见[工作原理](#工作原理)）。
- **跨会话记忆** — Agent不只在单次对话内记住你是谁，跨会话也记得：一份用户画像（风险偏好、投资风格、关注的股票代码）和一套分级TTL的调研结论存储（基本面/财报类事实约90天，新闻约30天；实时行情从不作为"记忆"持久化——每次都是实时召回）。两者都在每次请求时被召回，并且真正影响最终答案，不只是影响规划步骤（详见[工作原理](#工作原理)）。
- **LLM记忆抽取** — 每5轮对话，一个后台任务（不增加请求延迟）读取最近的对话内容并抽取结构化事实，抽取LLM的输出到真正落库之间，有确定性的schema校验和不可信内容围栏把关。
- **技能SOP库** — 四套研究playbook（估值、财务报表、行业对比、风险扫描）。它们的元数据目录常驻静态 system 前缀，模型自己判断哪份适用、再用 `load_sop` 工具取回正文，而不是靠一次独立的分类往返提前加载。这套机制究竟在多大程度上改变了实际问出的子问题，**目前无法量化**——见[量化评测](#量化评测)里的 SOP 一条。
- **免责声明，强制保证** — 每个回答末尾都会在生成之后由代码强制追加固定免责声明，不是靠prompt指令要求模型自己加，所以不会被模型漏掉。

## 快速开始

### 前置条件
- Docker Desktop（如果是WSL2，需要开启WSL集成）
- Python 3.11+（推荐用conda环境）
- Node.js 18+
- 一个DashScope（阿里云）API key 和一个Serper API key

### 1. 配置环境变量
把 `.env.example` 复制成 `.env` 并填入你自己的key：
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

### 2. 启动基础设施
```bash
docker compose up -d
```

### 3. 安装Python依赖
```bash
pip install -r requirements.txt
```

### 4. 抓取并索引金融语料
```bash
python scripts/fetch_filings.py       # SEC EDGAR财报(10-K/10-Q/8-K) -> data/filings/
python scripts/fetch_news.py          # 各股票的近期新闻 -> data/news/
python scripts/fetch_educational.py   # 精选科普参考文章 -> data/educational/
python scripts/index_finance.py       # 分块+向量化+把三者一起索引进ES的`finance_kb`
```

### 5. 启动后端
```bash
cd backend/app
uvicorn app_main:app --reload --port 8000
```

### 6. 启动前端
把 `frontend/.env.example` 复制成 `frontend/.env`：
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

打开 [http://localhost:5181](http://localhost:5181)。

## 生产部署

[在线demo](#在线体验)跑在同一个仓库里，在开发用的compose文件之上叠加了一层：

- `docker-compose.prod.yml` — 新增`backend`/`frontend`/`gateway`三个服务（分别由`backend/Dockerfile`、`frontend/Dockerfile`、`gateway/Dockerfile`构建），给每个服务钉死了`mem_limit`（基于真实负载下实测的容器内存校准出来的，不是拍脑袋估的），并且去掉了开发环境里`es01`/`pg`对宿主机端口的暴露。
- `gateway/` — 单一nginx容器是唯一的公网入口：TLS（Let's Encrypt，通过`certbot`两阶段引导解决证书和nginx启动顺序的鸡生蛋问题）、`/ai-search/*`反代到backend并支持SSE直通（关闭缓冲）、请求限流。
- `.github/workflows/deploy.yml` — 每次push：构建`backend`/`frontend`/`gateway`三个镜像；只有push到`master`时才会额外推送到GHCR并SSH登进服务器执行`pull`+`up -d`。部署用的SSH密钥只会跑这两条命令；业务密钥（`.env`）是一次性手动放到服务器上的，从不经过CI传输。

这不是一份"到处都能直接用"的通用部署模板——compose文件和网关配置是针对这个项目具体的服务结构写的，`mem_limit`的数值也是针对某一档特定虚拟机规格校准出来的。可以当作一个完整的实操范例参考，不建议直接照搬套用到别的项目上。

## 工作原理

```
用户提问
      ↓
  agent_plan()         ── LLM决定调用哪些工具，拆成子问题
      ↓
  process_actions()    ── 调用rag_search/finance_query/web_search；工具报错会
      ↓                    直接暴露给LLM，不会被吞掉
  should_continue()     ── 循环：LLM判断信息是否够了；不够的话决定下一步调用什么——
      ↓  (有上限的循环)    循环体本身（不是LLM）只负责给失控循环设一个安全上限
      ↓
  final_answer()        ── 通过SSE流式输出推理过程+最终答案
      ↓
  前端渲染思考链+最终答案
```

**工具选择规则：**
- 实时报价/市值/市盈率/基本面/新闻标题 → `finance_query`
- 财报内容/风险因素/新闻分析/概念解释 → `rag_search`
- 知识库没覆盖的最新市场动态 → `web_search`
- 与金融无关的话题 → 拒绝回答

**为什么这个循环是真正的agent循环，而不是写死的流水线：** 每一次继续/停止/重试的决策都读自LLM自己输出的结构化判断(`{sufficient, rationale, actions}`)，不是靠硬编码分支。一个安全上限（5次迭代）给失控循环兜底，但不会被误当成真正的LLM判断——触达上限而停止的情况，跟LLM主动发出停止信号的情况，日志里是分开记录的。工具调用失败会进入LLM自己能看到的对话记忆里，所以它能重试、换个方式，或者在最终答案里标注信息不完整，而不是后端悄悄把失败吞掉。

**跨语言混合检索：** `rag_search`在同一个Elasticsearch索引上组合两路信号（原生ES 8.11的`knn`+`query`，手写实现——不依赖RAGFlow）：
- **BM25**（`content_ltks`全文检索）——精确关键词匹配。
- **向量kNN**（`q_1024_vec`，text-embedding-v3，余弦相似度）——语义匹配和跨语言匹配。

两路的分数相加（向量分支做了加权平衡量级差异）；如果查询向量化失败，会优雅降级成只用BM25。合并后的候选结果再用qwen3-vl-rerank重排，最后用一个"上传时间新近度"加权把最终结果收窄到前5条。这套机制直接用[`eval/recall_validation.py`](eval/recall_validation.py)针对`finance_kb`语料库验证过，该脚本调用的正是`rag_search`生产环境实际用的同一套query构造代码：针对这个项目纯英文语料库（SEC财报、新闻、科普文章）的10个中文口语化金融问题，纯BM25召回率是**0%**（0/10），而混合检索（BM25+向量）召回率是**100%**（10/10）——具体查询和命中数见脚本。

**跨会话记忆：** 在调用`agent_plan()`之前，`final_answer()`会召回用户画像(`recall_user_profile`，`service/memory/profile.py`)，并且通过一个对中日韩文字容忍的正则(`_extract_tickers_loose`，`agent.py:416`，能捕获跟中文粘在一起的股票代码，因为`_TICKER_RE`的`\b`单词边界会漏掉比如"AAPL的股价"这种写法)从原始问题里提取股票代码，进而召回任何相关的、尚未过期的调研结论(`recall_all_conclusions`，`agent.py:429`)。两者都会被编织进规划prompt（这样agent可以跳过重复的数据获取），而且同一批召回的结论**同时也**会被拼接进最终答案的prompt——上一次会话里召回的一个事实真的可能出现在这一轮的答案里，不只是影响调用哪些工具。召回的内容都包在`<untrusted_context>`里，并带有"如果跟实时数据冲突，以实时数据为准"的明确指令，跟工具返回结果的处理方式一致。

每5轮对话，一个由`BackgroundTasks`调度的任务(`service/memory/extraction.py`)会读取最近的对话内容，让LLM抽取结构化事实（更新后的偏好、带时间戳的结论）。实时行情数据在进入校验之前就已经被代码层直接丢弃——它没道理被缓存成长期"记忆"。能存活下来的内容都经过确定性的schema校验（枚举值、股票代码/指标名称的正则、长度上限）才会落库，所以即便对抽取用的LLM发起一次成功的prompt注入，产出的最多是让人困惑的*内容*，没法写入不符合schema的值，也逃不出被沙箱化的prompt字符串。

**技能SOP库：** 四套playbook以纯Markdown文件的形式放在`service/agent/skills/`下（`valuation.md`、`financial_statement.md`、`industry_comparison.md`、`risk_scan.md`），各带YAML frontmatter和一份指标检查清单。`classify_skill()`(`agent.py:782`)是一次独立的LLM调用——刻意*没有*折叠进`agent_plan()`自己的那次调用里，因为等你知道该加载哪个技能的时候，已经来不及把它的正文注入进那同一次调用了——它会返回零个、一个，或者（代码层面强制上限，不管LLM实际返回什么）两个匹配的技能；技能正文会被加载(`load_skill()`，`agent.py:757`)并作为独立的标注区块注入进规划prompt。这套机制经过验证，确实会改变工具规划，不只是给prompt做装饰——详见[量化评测](#量化评测)。

## 技术栈

| 层次 | 技术 | 作用 |
|---|---|---|
| LLM | Qwen — qwen3.7-max（最终答案）、qwen-plus（规划/反思），通过`openai` SDK对接DashScope的OpenAI兼容接口 | 推理 + 工具决策 |
| Agent框架 | 自研 Plan→Act→Reflect→Answer 流水线（不用LangChain） | 工具编排 + 自我纠错 |
| 知识库 | Elasticsearch `finance_kb`（SEC财报+新闻+科普文章+用户上传文件）；text-embedding-v3做向量嵌入，qwen3-vl-rerank（原生`dashscope` SDK）做重排 | 混合检索（BM25+向量）+ 重排 |
| 实时数据 | yfinance（`service/finance/finance_tool.py`） | 报价/基本面/新闻 |
| 文档解析 | DeepDoc（版式/表格识别/OCR，基于onnxruntime） | PDF财报上传 → 表格感知的分块 |
| 网络搜索 | Serper API | 最新市场动态/兜底检索 |
| 后端 | FastAPI + PostgreSQL | API、SSE、会话与消息；`user_profiles`/`conclusion_memory`承载跨会话记忆 |
| 记忆与技能 | `service/memory/{profile,conclusion,extraction}.py`、`service/agent/skills/*.md` | 跨会话召回、LLM抽取流水线、SOP驱动的规划 |
| 前端 | React + TypeScript + Vite + Ant Design + Valtio | 聊天界面、流式渲染、文档管理 |
| 基础设施 | Docker Compose（本地开发用ES+PG；生产用完整技术栈+nginx网关+Let's Encrypt） | 本地依赖 / 生产托管 |
| CI/CD | GitHub Actions + GHCR | 每次push构建/推送镜像；`master`分支额外触发SSH部署（`pull`+`up -d`） |

## 项目结构

```
InvestPlus/
├── backend/
│   ├── Dockerfile                   # 生产镜像：依赖 → tiktoken/nltk预烘 → 应用代码（这个层顺序是为了让纯改代码时命中缓存）
│   └── app/
│       ├── app_main.py              # FastAPI入口
│       ├── router/
│       │   ├── chat_rt.py           # /chat SSE、/upload_files（.txt/.md/.pdf）、/get_files、/delete_file
│       │   └── history_rt.py        # /sessions、/messages
│       ├── service/
│       │   ├── agent/
│       │   │   ├── agent.py         # Agent流水线（Plan→Act→Reflect→Answer）+ 记忆/技能召回与注入
│       │   │   └── skills/          # SOP playbook：valuation/financial_statement/industry_comparison/risk_scan.md
│       │   ├── memory/
│       │   │   ├── profile.py       # recall_user_profile / upsert_user_profile
│       │   │   ├── conclusion.py    # recall_conclusion_facts / upsert_conclusion_fact（分级TTL）
│       │   │   └── extraction.py    # extract_memory() —— 每5轮触发的LLM抽取流水线
│       │   ├── finance/              # finance_tool.py —— 实时yfinance报价/基本面/新闻
│       │   ├── web_search/          # Serper网络搜索工具
│       │   └── core/
│       │       ├── file_parse.py    # .txt/.md分块器 + .pdf DeepDoc流水线 -> ES索引器
│       │       ├── deepdoc/         # PDF解析器（版式/表格/OCR）
│       │       └── rag/             # 分词器/nlp工具 + res/deepdoc模型权重
│       ├── models/memory.py         # SQLAlchemy模型：UserProfile、ConclusionMemory
│       ├── schemas/chat.py
│       └── utils/database.py
│   └── tests/
│       ├── test_agent_loop.py       # 循环机制单元测试（should_continue、错误传播）+ 合流步骤测试
│       ├── test_chat_router.py      # /chat SSE + 相关路由端点
│       ├── test_history_router.py   # /sessions、/messages
│       ├── test_finance_tool.py     # yfinance封装、失败降级、股票代码缓存
│       ├── test_file_parse.py       # .txt/.md/.pdf分块 + ES索引
│       ├── test_pdf_parser.py       # DeepDoc PDF解析器
│       ├── test_es_client.py        # Elasticsearch客户端单例/配置
│       ├── test_knowledgebase_operations.py
│       ├── test_index_finance.py    # 批量语料索引器
│       ├── test_e2e_finance.py      # 针对运行中后端的真实端到端冒烟测试
│       ├── test_memory_layer.py     # 画像/结论的读写 + 抽取校验
│       ├── test_memory_recall.py    # 中日韩文字容忍的股票代码提取 + 召回接线
│       ├── test_memory_scheduling.py # 判别性的BackgroundTasks触发测试
│       └── test_skill_sop_and_disclaimer.py
├── eval/                             # 量化Agent/RAG评测框架（见下文）
├── frontend/
│   ├── Dockerfile                   # 多阶段构建：npm build -> 静态资源由nginx托管
│   └── src/
│       ├── i18n.tsx                 # 中英双语文案
│       ├── components/
│       │   ├── header-bar/          # 带中/EN切换的头部
│       │   └── sender/              # 输入框 + 文件附件
│       └── pages/
│           ├── chat/                # 带SSE流式的聊天页
│           └── repository/          # 文档管理
├── gateway/                          # 生产入口：nginx TLS/反代/限流/Basic Auth
│   ├── Dockerfile
│   ├── nginx.conf                   # 生产配置（TLS，真实域名）
│   └── nginx.local.conf             # 本地栈对应版本（纯HTTP，无certbot）
├── .github/workflows/deploy.yml     # CI：每次push构建全部3个镜像；master分支额外推送到GHCR + SSH部署
├── scripts/                          # 金融语料抓取/索引脚本（fetch_filings/news/educational、index_finance）
├── data/                             # 抓取到的金融语料（filings/news/educational），已索引进`finance_kb`
├── docker-compose.yml                # ES + PostgreSQL（共享基础）
├── docker-compose.local.yml          # + backend/frontend/gateway，用于本地全栈开发（纯HTTP）
├── docker-compose.prod.yml           # + backend/frontend/gateway/certbot，用于生产（TLS、mem_limit钉死）
└── .env                              # API key和配置
```

## 量化评测

一套可复现的评测框架（`eval/`）用真实的agent/RAG/Elasticsearch逻辑（不mock）端到端驱动运行中的后端，针对从实际索引语料构建的标注数据集评测：

| 指标 | 结果 | 依据 |
|---|---|---|
| 工具路由平均命中率 | **74.5%** | 17 题 × **3 次采样**。其中稳定命中 10 题、稳定失败 3 题、**翻转 4 题**（同一份代码上时对时错） |
| 首个实质判断延迟 | **均值 2.93s**（p50 2.63s / p90 4.86s） | 从 `POST /chat` 到第一条工具调用事件。这是衡量响应性的那个数 |
| 完整响应延迟 | 均值 32.6s（p50 31.9s / p90 55.0s） | 32 次真实流式请求，含 Plan→Act→Reflect→Answer 全程 |
| RAG 检索/回答准确率 | 13/15 | 基于事实的问答对，针对实际的财报/新闻/科普语料核对 |
| 边界场景健壮性 | 5/5 | 空输入、超长输入、无效股票代码、无关话题、不存在的 session |

**下列数字不可引用，理由写在这里而不是省略：**

- **「首字延迟」/「首次反馈延迟」**：自 [`448b831`](.) 起，第一条 SSE 事件是后端在任何 LLM 调用之前发出的受理回执，实测恒为 0.00s。它只证明连接已建立，不度量模型、检索或工具的任何行为。要谈响应性请用上表的「首个实质判断延迟」。
- **单次采样的路由严格准确率**：4/17 的题在同一份代码上会翻转，使单次数字带有约 **±24 个百分点**的摆动。任何小于该幅度的前后对照都读不出结论，因此本 README 只给多次采样的平均命中率。
- **SOP 注入的覆盖率提升**：两把尺子都已知失效。旧口径在子问题文字里数关键词，而 `finance_tool` 不解析具体指标——`"AAPL PE ratio"` 与 `"AAPL fundamentals"` 返回逐字节相同的结果，于是它奖励啰嗦而非信息量。改成按工具实际返回内容打分之后，同一批数据的提升从 +52.8pp 降到 +11.1pp，但新口径又会饱和（基本面卡固定只含 5 个估值概念中的 2 个，得分只有两档刻度）。评分维度重设待办。

**延迟的构成值得单独说一句。**思考内容均值 1810 字符，可见回答均值 486 字符，前者是后者的 **3.7 倍**，与总延迟相关 r=0.90。全程 32.6s 里，回答开始流式输出之后只剩 3.7s。因此压缩可见回答长度几乎动不了总延迟，真正的杠杆是回答调用的 `enable_thinking`。

方法论、完整数据集和原始记录：[`eval/report.md`](eval/report.md)、[`eval/dataset.py`](eval/dataset.py)、[`eval/results.json`](eval/results.json)。用 `python eval/run_eval.py --routing-samples 3` 针对运行中的后端重新跑一遍。

**诚实说明：** 语料库是这个项目自带的测试数据（部分由AI生成，日期设定在未来）——RAG准确率衡量的是对已索引语料的忠实度，不是针对真实世界金融数据的验证。

## 已知局限

- **三道稳定失败的路由题** — 3 次采样全错的那三道，所以是真问题而不是采样抖动。`route-05`（"什么是自由现金流？"）给一道知识库本就能答的概念题多调了 `web_search`；`route-11`（"今天全球有什么重要的财经新闻？"）一个工具都不调；`route-17` 把复合题里的新闻半边发给了 `rag_search` 而不是 `web_search`。已经试过一次并回退：按"最近/最新/今天"这类时间词划边界，修好了 `route-11` 和 `route-17`，却把一道问"谷歌**最近的** 8-K"的对照题改坏了——8-K 是归档文件，不是真实世界的时效动态。边界必须按答案的载体划（归档文档走 `rag_search`，当下动态走 `web_search`），不能按题面听起来时不时效划。
- **文件上传的PDF解析** — DeepDoc PDF流水线接在了用户通过`/upload_files`上传财报的路径上，但批量语料索引器（`scripts/index_finance.py`）是直接从SEC EDGAR原生的HTML（iXBRL）格式解析财报，而不是走PDF流水线，因为EDGAR不以PDF格式提供现代财报（见`index_finance.py`模块文档字符串）。
- **抽取只按轮数触发，不按会话结束触发** — 这套请求-响应架构里没有可靠的"会话已结束"信号（没有可以挂钩的持久连接），所以记忆抽取是每5轮触发一次，而不是按早期设计草图设想的"会话结束 或 满N轮"这种或条件触发。一段在窗口内第*N*-1轮就结束的对话，尾部内容永远不会被抽取。
- **`BackgroundTasks`抽取任务不持久化也不重试** — 如果进程在任务调度和实际执行之间重启，那一批事实就丢了；同一会话里下一个5轮边界不受影响（窗口之间不重叠），所以影响范围是"部分记忆没被捕获"，不是数据损坏。
- **召回路径里股票代码和缩写的歧义** — 用于调研结论召回的中日韩文字容忍股票代码提取器（不是`finance_tool()`用在已拆解子问题上的那个更严格的版本）无法区分一个常见金融缩写和拼写相同的真实股票代码（`AI`既是"人工智能"也是C3.ai的股票代码）；最坏情况是一条不相关的旧结论作为背景信息被带出来，而召回prompt本来就已经把这类内容当作"可能过时"来处理。
- **记忆召回里写死了单用户假设** — `chat_rt.py`里硬编码的`USER_ID`被用于画像召回，而抽取环节则是从session自己的记录里推导出写入用的用户——这两者目前恰好一致，但如果以后要支持真正的多用户，需要重新梳理。
- **聊天界面没有适配手机** — 核心聊天布局（`components/page-layout`）在主内容区域写死了`min-width: 600px`，右侧还有一个固定`408px`的侧栏；在真实手机屏幕宽度下会溢出/被挤压，而不是自适应重排。落地页本身的响应式做得还算合理，但全局布局外壳（`layout/base`）会给所有路由套上一个固定`100px`宽度的侧边栏，跟屏幕宽度无关。目前聊天页没有任何`@media`断点覆盖——桌面端是唯一被完整支持的目标。
- **没有对话历史管理界面** — `session_id`只存在URL里（`/chat/:id`），不写入`localStorage`；应用本身没有浏览或删除历史会话的入口（服务端有一个`DELETE /sessions`接口，但前端没有任何地方调用它）。每次访问都是全新会话，旧会话会无限期留在Postgres里，没有TTL或清理机制。

## 路线图

目前的MVP覆盖单支股票/市场分析（AAPL/MSFT/GOOGL）。这在架构上是一个更广泛的投研copilot的基础——组合层面的推理、多资产对比——可以复用同一套工具/RAG层。

## 许可 / 版权说明

应用和Agent代码为原创；混合检索（`agent.py`里的`rag_search`）是直接手写在原生Elasticsearch之上，不依赖RAGFlow。但PDF解析流水线（`service/core/deepdoc`、`service/core/rag`）是从[RAGFlow](https://github.com/infiniflow/ragflow)移植而来（Apache License 2.0，版权归The InfiniFlow Authors所有）——具体见该目录下的license头。财报数据来自[SEC EDGAR](https://www.sec.gov/edgar)，行情数据来自[yfinance](https://github.com/ranaroussi/yfinance)。LLM通过阿里云DashScope提供。
