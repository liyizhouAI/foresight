# Foresight 先见之明 — 产品需求文档 (PRD)

> **版本**：v0.3.3 — 2026-04-16 CustomGraphBuilder + 一键部署 + CDN SPA 修复
> **基线**：基于 [MiroFish](https://github.com/666ghj/MiroFish) v0.1.2 二次开发，已大量重构。

---

## 1. 产品定位

**Foresight 是一个把"需要预测的未知"变成"可演化的数字沙盘"的群体智能引擎。**

用户上传任何一份"信号"——一段视频文案、一份政策草案、一次金融事件复盘、一段小说背景——Foresight 自动构建该信号所属世界的知识图谱，孵化出几百个有完整人格、记忆、行为模式的虚拟 Agent，让他们在虚拟社交平台上自由互动、扩散、对抗、共鸣，最后输出一份"如果这件事真的发生，世界会变成什么样"的详尽预测报告。

**核心命题**：让"未来"在数字沙盘里先演练一遍，让决策在百战模拟之后才下刀。

### 三种使用形态

| 形态 | 用户 | 典型问题 | 输出 |
|---|---|---|---|
| **单次预测** | 个人 / 临时项目 | "这条视频发出去会火吗？" | 一份报告 + 可回放的传播沙盘 |
| **建模 + 复用** | 团队长期使用 | "我有一批 200 人的目标受众样本，每周给我跑 5 条新内容看哪个最容易出圈" | 同一批 agent 反复跑不同 initial_posts |
| **多租户 SaaS**（v0.4 路线图） | 客户分账户 | "金融预测 / 舆情扩散 / 关系发展 各建一套独立沙盘" | 子账户体系 + 按次计费 + 项目隔离 |

---

## 2. 产品愿景：从工具到平台

### 2.1 v0.3 现状（已实现）

一个**单租户**的端到端预测流水线：上传文档 → 图谱 → 人设 → 配置 → 模拟 → 报告 → 回放 → 互动。

### 2.2 v0.4 目标（下一个大版本）

**Foresight 升级为多领域可定制的预测系统。** 不再只服务"舆情扩散"一个场景，而是抽象为**"任何可被多 agent 互动建模的预测问题"**：

| 应用领域 | 输入信号 | Agent 类型 | 预测输出 |
|---|---|---|---|
| **内容传播预测** | 视频逐字稿 / 帖子文案 | 200 个画像各异的目标受众 | 触达率 / 互动率 / 传播路径 / 爆款概率 |
| **舆情扩散预测** | 突发事件 / 政策草案 | 不同立场的意见领袖 + 普通群众 | 舆论走向 / 关键拐点 / 情绪曲线 |
| **金融市场预测** | 财报 / 政策 / 黑天鹅事件 | 散户 / 机构 / 量化 / 媒体 | 价格反应 / 资金流向 / 板块联动 |
| **人际关系发展** | 角色背景 / 起始事件 | 故事中的所有角色 | 关系演化树 / 关键转折 / 多结局 |
| **品牌危机推演** | 危机事件 + 公关方案 | 用户 / 媒体 / 监管 / 竞品 | 不同应对策略下的舆情走向 |

**核心抽象**：每个领域 = 一组（领域语料 + 领域 agent 库 + 领域平台规则 + 领域评估指标）。Foresight 提供**通用的工作流编排**，领域知识用配置即可注入。

### 2.3 v0.5 商业化（远期）

- 子账户体系（org / user / project 三级权限）
- 按模拟次数 / agent 数 / 报告深度计费
- 模型 fork & 对比模式（A/B 内容对比传播效率）
- 数据隔离 + 合规审计

---

## 3. 系统架构（v0.3 实际部署）

```
                                                    ┌─────────────────────┐
                                                    │  M-flow（记忆系统） │
                                                    │  踩坑/经验/凭证记录 │
                                                    └─────────────────────┘
用户浏览器
  │
  ├── 前端 (Vue 3 + Vite)                          
  │     部署：腾讯云 COS + CDN
  │     域名：foresight.yizhou.chat
  │     新增页面：/simulation/:id/replay（Manus 式过程回放）
  │
  └── HTTPS → api.foresight.yizhou.chat (Nginx)
        │
        └── Backend Flask (5001)                    服务器：腾讯云 2C8G
              │                                      OS：Ubuntu 24.04
              │                                      Python：3.11.15 (uv 管理)
              │                                      venv：/opt/foresight/backend/.venv-311
              │
              ├── LLM API：智谱 GLM-4-Flash         （之前用 MiniMax M2.7，已弃）
              │     用途：本体、画像、配置、报告、模拟决策
              │     Endpoint：https://open.bigmodel.cn/api/paas/v4/
              │
              ├── Knowledge Graph：CustomGraphBuilder + Neo4j（v0.3.2 替代 Graphiti）
              │     部署：Docker 容器 neo4j:5.26-community
              │     图谱构建 LLM：GLM-4-Flash（同主 LLM，自带 retry + fallback）
              │     Embedding：BAAI/bge-m3 via SiliconFlow（仅下游检索用）
              │
              ├── HF Hub Mirror：hf-mirror.com      OASIS 推荐模型 twhin-bert-base
              │
              └── OASIS 模拟引擎                    fork 自 camel-oasis 0.2.5
                    支持 Twitter / Reddit 双平台并行
                    🚧 国内平台抽象层：v0.4 路线图（抖音/视频号/小红书/微博）
```

### 3.1 关键基础设施决策（v0.3 沉淀的经验）

| 决策点 | 当前选择 | 弃用方案 | 原因 |
|---|---|---|---|
| LLM | 智谱 GLM-4-Flash | MiniMax M2.7 / GPT-4o-mini | Flash 单次延迟 0.5-1s，128K context |
| 图谱构建 | **CustomGraphBuilder**（自研） | Graphiti + Qwen/GLM | Graphiti 与非 OpenAI LLM 兼容性黑洞（详见附录 C） |
| 知识图谱存储 | 自托管 Neo4j | Zep Cloud | 摆脱外部依赖、可控、免月费 |
| Python | 3.11（uv 管理） | 系统 3.12 | camel-oasis<3.12 不兼容 3.12 |
| 包源 | 腾讯云 PyPI 镜像 | 直连 PyPI | 国内服务器直连慢 100x |
| HF 模型源 | hf-mirror.com | huggingface.co | 国内服务器连不上 hf 主站 |
| Agent 数甜点 | **200 agents** | 503（默认） | 8G 内存上限 + 95% 置信区间足够 |
| 运行参数 | semaphore=100 / 双平台 | semaphore=30 / 单平台 | 8G 升级后可承载 |

---

## 4. 核心功能流水线（5 步 + 1 回放）

### Step 1: 知识图谱构建

**输入**：上传文档（PDF/MD/TXT/DOCX）+ 模拟需求自然语言描述

**流程**：
1. 文档解析 → 文本提取
2. LLM 分析全文 → 生成本体（10 个实体类型 + 6-10 个关系类型）
3. 文本分块 → 批量调用 Graphiti → 写入 Neo4j
4. 返回图谱可视化（节点 + 边）

**API**：
- `POST /api/graph/ontology/generate`
- `POST /api/graph/build`
- `GET /api/graph/task/<task_id>`

### Step 2: Agent 人设生成

**输入**：已构建的知识图谱

**流程**：
1. 从 Neo4j 读取图谱实体与关系
2. 按实体类型筛选，调用 LLM 为每个实体生成 OASIS Agent Profile
3. 每个 profile 含：人设故事 / MBTI / 年龄 / 职业 / 兴趣话题 / 活跃时段 / 互动倾向
4. 实时写入 `reddit_profiles.json` 和 `twitter_profiles.csv`

**新功能**（v0.3 新增）：
- **加速完成按钮**：右上角"加速完成"，用户可在生成到任意数量时立即停止剩余生成，使用已生成的 profile 进入下一步

**API**：`POST /api/simulation/prepare`

### Step 3: 模拟配置生成

**输入**：profiles + 模拟需求 + 文档原文

**流程**：
1. LLM 智能生成时间配置（peak hours / off-peak hours / 活跃度系数）
2. LLM 智能生成事件配置（initial_posts 列表 + 轮次事件）
3. LLM 为每个 agent 分配活跃时段、互动概率
4. 输出 `simulation_config.json`

### Step 4: 双平台模拟运行

**输入**：profiles + simulation_config

**流程**：
1. 启动 OASIS Twitter env + Reddit env 并行（asyncio.gather）
2. 每轮按时间窗口激活若干 agent
3. 每个激活的 agent 调用 LLM 生成行为（发帖 / 评论 / 点赞 / 转发 / 关注）
4. 实时写入 `twitter/actions.jsonl` 和 `reddit/actions.jsonl`
5. 每平台限制 semaphore=100 防止 API 过载

**性能指标**（200 agents 双平台 8G 服务器）：
- 启动 + tokenizer 加载：~30-60s
- 每轮：~30-60s（取决于活跃 agent 数）
- 15 rounds 完整跑完：~10-15 分钟

**API**：
- `POST /api/simulation/start` — 启动
- `POST /api/simulation/stop` — 停止
- `GET /api/simulation/<id>/run-status/detail` — 实时状态

**新功能**（v0.3 新增）：
- **后端 SIGTERM 误杀子进程 bug 修复**：之前重启 Flask 会连带杀掉正在跑的模拟，已通过让 `register_cleanup` 变为 no-op 修复，现在可以热更新后端代码不影响运行中的模拟。

### Step 5: 报告生成

**输入**：完整模拟结果 + 知识图谱

**流程**：
1. LLM 规划报告大纲（5 个章节）
2. 每章节 ReACT 循环（推理 → 工具调用 → 生成）
3. 工具：图谱搜索（InsightForge / Panorama）/ 节点详情 / agent 行为统计
4. 输出结构化 Markdown 报告

**API**：`POST /api/report/generate`

> Token 消耗最大的环节，单次完整报告约 80-150K tokens。

### Step 6（新增）: Manus 式过程回放

**v0.3 新增的核心功能**。把整个 Foresight 工作流（Step 1-5）做成可拖拽 / 可播放的可视化时间线，方便给客户、合作方、自己复盘演示。

**界面布局**：

```
┌─────────────────────────────────────────────────────┐
│ ← 返回   foresight 回放  sim_xxxx   [running]       │
├─────────┬──────────────────────────────┬────────────┤
│ 工作流  │  当前动作（大卡片）           │ 全局统计   │
│ 时间线  │   ┌─────────────────────┐    │            │
│         │   │ 👤 90后 (#6)         │    │ 总动作 N   │
│ ● 步骤1 │   │ 📱 reddit            │    │ rounds 8   │
│ │ 文档  │   │ ✏️ CREATE_POST       │    │            │
│ │       │   │ "芒格说复利..."       │    │ 类型分布   │
│ ● 步骤2 │   └─────────────────────┘    │  POST  85%│
│ │ 图谱  │                              │  LIKE  12%│
│ │       │   动作流（滚动 30 条）        │            │
│ ● 步骤3 │   ┌─────────────────────┐    │ Top Agents │
│ │ 人设  │   │ r03 90后 ✏️ ...      │    │ 90后    8 │
│ │       │   │ r03 70后 💬 ...      │    │ 00后    6 │
│ ● 步骤4 │   │ r04 AI   📤 ...      │    │            │
│ │ 配置  │   └─────────────────────┘    │ 平台分布   │
│ │       │                              │ TW 17 RD 8 │
│ ● 步骤5 │                              │            │
│   模拟  │                              │            │
├─────────┴──────────────────────────────┴────────────┤
│ ⏮ ▶ ⏭   ━━━━━●─────  Round 8/15  Day 1 08:00       │
│            速度 0.5x · 1x · 2x · 5x · 10x           │
└─────────────────────────────────────────────────────┘
```

**核心能力**：
- 左栏：5 步工作流时间线（带状态 + 元数据）
- 中上：当前动作大卡片（agent 头像 + 内容 + 平台/类型 tag）
- 中下：动作流滚动（最近 30 条，可点击跳转）
- 右栏：聚合统计（总数 / 类型分布 bar / Top 8 agents / 平台分布卡）
- 底部：scrubber 时间轴 + 播放控件 + 5 档速度

**数据源**：`GET /api/simulation/:id/replay` 一次性返回所有数据，前端无需多次请求。

**最新 run 过滤**：actions.jsonl 是 append-only 文件，多次 run 会累积。后端通过扫描最近一次 `simulation_start` 事件的时间戳，过滤掉历史 run 残留 actions，保证回放只显示最新一次。

---

## 4.5 Token 用量追踪与成本估算（v0.3 新增 · 内部用）

为了支持后续定价决策和成本控制，v0.3 新增 token 追踪模块。**销售给客户的版本需要移除此 blueprint 注册**（去掉 `app/__init__.py` 里的 `usage_bp` 即可）。

### 工作机制

- `backend/app/utils/token_tracker.py` 提供进程内全局 stage→model→tokens 计数器
- `LLMClient` 每次 `chat()` 自动 record 一次 `usage.prompt_tokens / completion_tokens`
- 各 API 端点在入口处 `token_tracker.set_stage("step1_ontology")` 等
- 价格表内置在 `PRICING` 字典，覆盖 GLM / SiliconFlow / MiniMax / OpenAI / Anthropic 主流模型

### Stage 命名

| Stage | 触发位置 | 说明 |
|---|---|---|
| `step1_ontology` | `POST /api/graph/ontology/generate` | 文档分析与本体生成 |
| `step2_graph_build` | `POST /api/graph/build` | Graphiti 图谱构建（含 LLM 提取实体） |
| `step3_prepare` | `POST /api/simulation/prepare` | Profile 生成 + 模拟配置生成 |
| `step4_simulation` | OASIS 子进程（**不在 Flask 内**） | 需要走 `estimate-simulation` API 估算 |
| `step5_report` | `POST /api/report/generate` | 报告 ReACT 多轮调用 |

### API

| 端点 | 用途 |
|---|---|
| `GET /api/usage/summary` | 当前累计统计：每个 stage 的 prompt/completion tokens + 估算成本（CNY） |
| `POST /api/usage/reset` | 清空（可指定 stage） |
| `GET /api/usage/estimate-simulation?rounds=15&active_agents_per_round=10` | 估算 OASIS 模拟成本（无法精确测） |
| `POST /api/usage/set-stage` | 手动切 stage（测试用） |

### 局限

1. **OASIS 模拟子进程的 LLM 调用无法被 Flask 进程的 tracker 捕获**（camel-ai 用自己的 client）。需要走 estimate API 用经验公式估算。
2. **进程重启会丢失数据**。如需持久化，加 `reset()` 前 dump 到 JSON 文件即可。
3. **价格表是 2026-04 价格快照**，需要定期更新 `PRICING` 字典。

### 典型 Foresight 单次完整流水线成本估算（200 agents / 15 rounds / GLM-4-Flash）

| Stage | Tokens 范围 | CNY 估算 |
|---|---|---|
| Step 1 本体生成 | 5K-15K | 0.001-0.003 |
| Step 2 图谱构建 | 50K-200K | 0.005-0.020 |
| Step 3 Profile + Config | 100K-300K | 0.010-0.030 |
| Step 4 模拟 (15 rounds) | 1M-3M | 0.10-0.30 |
| Step 5 报告生成 | 80K-150K | 0.008-0.015 |
| **合计** | **~1.2M-3.7M** | **~0.12-0.37 元** |

> 关键洞察：**模拟运行 (Step 4) 占总成本的 80%+**，但因为 GLM-4-Flash 单价极低，单次完整流水线 < 0.5 元 RMB。这给定价留了巨大空间：以成本 0.5 元 / 次，售价 5-50 元 / 次给客户都是合理的（取决于客户类型与定制化程度）。

---

## 5. v0.4 路线图（下一个大版本要做的事）

按优先级：

### P0：国内平台抽象层

**痛点**：当前 Twitter + Reddit 是欧美社交语境，国内 IP / 内容 / 客户都不匹配。

**目标**：支持抖音 / 视频号 / 小红书 / 微博 / 公众号 5 个国内平台。

**两条路径**：

| 路径 A（快速 MVP，2-3 周） | 路径 B（真模拟，1-2 月） |
|---|---|
| 基于 OASIS Reddit 模式 fork 一份"通用国内平台"虚拟实现 | 抛弃 OASIS，自研 platform engine |
| 不真正模拟抖音 ML 算法，用参数化传播模型 | 真模拟抖音 FYP / 视频号双引擎 / 小红书 tag 聚类 |
| LLM 决定 agent 互动 + 配置文件定义平台规则参数 | 行业报告训练参数 + 黑盒推荐算法逼近 |
| 可申请客户付费试点 | 可申请专利 / 学术发表 |

**先走路径 A**，3 周内可演示。客户付费数据反哺路径 B。

**配置形态（设计稿）**：

```json
{
  "platforms": [
    {
      "id": "douyin",
      "type": "short_video",
      "weight": 0.45,
      "rules": {
        "recommendation": "fyp_engagement_loop",
        "viral_threshold": 0.08,
        "interaction_types": ["like", "comment", "share", "follow", "watch_full"],
        "key_features": ["video_completion_rate", "comment_density", "share_velocity"]
      }
    },
    { "id": "xiaohongshu", "type": "lifestyle_feed", "weight": 0.25, "rules": {...} },
    { "id": "wechat_video", "type": "social_graph_video", "weight": 0.15, "rules": {...} },
    { "id": "weibo", "type": "broadcast_micro_blog", "weight": 0.10, "rules": {...} },
    { "id": "wechat_official", "type": "subscription_long_form", "weight": 0.05, "rules": {...} }
  ]
}
```

### P1：模型复用 / Fork 模拟

**痛点**：现在每次跑模拟都要走完 Step 1-4，重复劳动。

**目标**：基于已建好的 simulation 一键 fork 一个新版本，只换 `event_config.initial_posts` 即可。

**功能点**：
- "Fork as Template" 按钮
- 模板库：保存通过验证的 sim 作为预设
- A/B 对比模式：两条新内容并排跑，结果并排展示

### P2：多租户 SaaS 改造

**功能模块**（需要派出 8 个并行 sub-agent 协同开发）：

| Sub-Agent | 模块 | 任务 |
|---|---|---|
| Architect | 多租户架构 | PostgreSQL schema 隔离 / API gateway / RBAC 设计 |
| Backend Engineer | API 改造 | 加 user_id / org_id / billing 字段，所有数据按租户隔离 |
| Frontend Engineer | UI 改造 | 登录 / 注册 / dashboard / 子账户管理界面 |
| Platform Engine | 平台抽象 | 上面 P0 的国内平台抽象层落地 |
| Auth & Security | 认证 | 接 Better Auth / OAuth / API key 发放 |
| Billing | 计费 | 接微信 / 支付宝 / Stripe，按模拟次数 / agent 数计费 |
| DevOps | 容器化 | Docker + k8s + 监控 + 扩容策略 |
| PM/Critic | 全程 review | 商业目标对齐 + 架构 review |

### P3：稳定性 / 运维改进

- ✅ Backend SIGTERM 误杀子进程 bug（v0.3 已修）
- ⏳ 子进程心跳超时：当前 simulation 子进程挂掉后 state 不会自动更新成 failed，需要加心跳检测
- ⏳ 模拟运行内存预算检查：启动前根据 agent 数 + 平台数预估内存，超出可用内存时拒绝启动
- ⏳ Replay actions.jsonl 自动清理：每次新 run 启动前清空旧文件，避免历史残留
- ⏳ 多模拟并发支持：单服务器同时跑 2-3 个 sim（需要更大内存或更精细资源调度）

---

## 6. 技术栈

### 前端

| 技术 | 版本 | 用途 |
|---|---|---|
| Vue 3 | 3.5+ | UI 框架（Composition API + script setup） |
| Vite | 7.x | 构建工具 |
| Vue Router 4 | - | 路由 |
| vue-i18n | 9.x | 中英双语 |
| D3.js / Force Graph | - | 图谱可视化 |
| 字体 | Space Grotesk + Noto Sans SC + JetBrains Mono | 设计语言 |

### 后端

| 技术 | 版本 | 用途 |
|---|---|---|
| Python | 3.11.15 (uv 管理) | 运行时 |
| Flask | 3.1.3 | Web 框架 |
| OpenAI SDK | - | LLM 客户端（兼容智谱/MiniMax/SiliconFlow） |
| camel-ai | 0.2.78 | OASIS 依赖 |
| camel-oasis | 0.2.5 | 社交模拟引擎 |
| graphiti-core | - | Neo4j 图谱构建框架 |
| transformers + torch | - | OASIS 内置 twhin-bert-base |
| neo4j-driver | - | Neo4j 客户端 |

### 部署

| 组件 | 平台 | 说明 |
|---|---|---|
| 前端静态 | 腾讯云 COS + CDN | foresight.yizhou.chat |
| SSL 证书 | acme.sh / Let's Encrypt | 自动续期 |
| 后端 | 腾讯云轻量 2C8G Ubuntu 24.04 | api.foresight.yizhou.chat → 127.0.0.1:5001 |
| Neo4j | Docker container neo4j:5.26-community | bolt://localhost:7687 |
| 进程管理 | nohup + disown（无 systemd / 无 docker） | 启动命令见下 |

**Backend 启动命令**：

```bash
cd /opt/foresight/backend && \
  nohup ./.venv-311/bin/python run.py --host 0.0.0.0 \
    >> logs/server.log 2>&1 < /dev/null & \
  disown
```

---

## 7. 配置项

```env
# ========== LLM ==========
# 智谱 GLM-4-Flash（高吞吐低延迟，OASIS 模拟首选）
LLM_API_KEY=<智谱 API Key>
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL_NAME=glm-4-flash
# 可选升级：glm-4-flashx / glm-4-air / glm-4-plus（同 endpoint，质量↑速度↓）

# 双 LLM 加速（可选，让两平台用不同 provider 分摊 RPM）
LLM_BOOST_API_KEY=
LLM_BOOST_BASE_URL=
LLM_BOOST_MODEL_NAME=

# ========== Neo4j（自托管 Graphiti 后端） ==========
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<密码>

# ========== Graphiti LLM（图谱构建） ==========
GRAPHITI_LLM_API_KEY=<SiliconFlow API Key>
GRAPHITI_LLM_BASE_URL=https://api.siliconflow.cn/v1
GRAPHITI_LLM_MODEL=Qwen/Qwen2.5-32B-Instruct

# ========== Embedding ==========
EMBEDDING_API_KEY=<SiliconFlow API Key>
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3

# ========== HuggingFace 镜像（必填，国内服务器） ==========
HF_ENDPOINT=https://hf-mirror.com

# ========== Flask ==========
FLASK_DEBUG=False
```

---

## 8. v0.3 当前状态与已交付

### v0.3.3（2026-04-16 CustomGraphBuilder + 一键部署 + CDN 修复）

- [x] **CustomGraphBuilder 替代 Graphiti**（v0.3.2 核心交付）
  - 完全自研的图谱构建器，不依赖 graphiti-core 库
  - 每 chunk 单次 LLM 调用（Graphiti 需要 4-5 次）→ 速度 4-5x
  - ThreadPoolExecutor 10 并发 → 194 chunks 从 10 分钟降到 ~2 分钟
  - 直接用 cypher MERGE 写 Neo4j → 无 Graphiti 嵌套 dict / context overflow 等兼容性问题
  - 使用 Foresight LLMClient 自带 retry + fallback + token tracker
  - 下游 `get_all_nodes / get_all_edges / filter_defined_entities` 完全兼容
  - 文件：`backend/app/services/custom_graph_builder.py`

- [x] **一键部署脚本** `scripts/deploy.sh`
  - `--backend`：rsync → 语法检查 → kill/restart Flask → health verify
  - `--frontend`：vite build → coscmd upload → tccli CDN purge
  - `--full`：两个都做
  - `--dry-run`：预演
  - 处理路径空格 / sudo rsync / Flask 存活检查

- [x] **CDN SPA 路由 fallback**
  - 问题：Vue Router history 模式，COS 上子路径全部 404
  - 修复：`tccli cdn UpdateDomainConfig` 设置 404 → 302 跳转 `/index.html`
  - 永久配置，deploy.sh 不需要每次重新设

- [x] **前端首次正式部署到腾讯云 COS**
  - `coscmd upload -r dist/ /` → bucket `foresight-1317962478`
  - CDN purge → `tccli cdn PurgePathCache`
  - 包含 v0.3 所有前端改动（replay UI / 加速完成按钮 / 路由修复）

- [x] **Graphiti 兼容层保留**
  - graphiti_client.py 中的 5 层 monkey-patch 保留（driver / reranker / embedder / EntityNode / bulk_utils）
  - 这些只影响旧 Graphiti 代码路径（add_episode / add_episodes_batch）
  - 新 CustomGraphBuilder 完全绕过，不受影响

### v0.3.1 hotfix（2026-04-15 生产链路打通）

经过一次完整的端到端测试，修复了 7 个阻塞生产跑通的 bug：

- [x] **Manus 式沉浸视图重构** — 回放界面从三栏分析面板 → Manus 风格单栏 cinematic 视图
  - 顶部 breadcrumb、浏览器外壳 + 平台原生帖子卡片、Jump to live 按钮、live 指示灯
  - 右上角 ◫/▦ 可切回三栏分析视图
  - 自动轮询：sim running 时每 10s 拉数据
  - 文件：`frontend/src/views/SimulationReplayView.vue`

- [x] **LLM 客户端指数退避重试** — 识别 `RateLimitError / 429 / 5xx / 1302 / 超时`，5 次重试 1→2→4→8→16s 带随机抖动
  - 文件：`backend/app/utils/llm_client.py`

- [x] **GLM → Qwen 32B 双 LLM 降级 fallback** — 主 LLM 重试耗尽后自动切 SiliconFlow Qwen 32B 单次兜底，解决 GLM 低 RPM 配额的间歇性限流
  - 文件：`backend/app/services/ontology_generator.py`

- [x] **Qwen 32B 上下文爆修复** — `MAX_TEXT_LENGTH_FOR_LLM` 50000 → 28000 chars，保证 prompt+response < 32768 tokens
  - 文件：`backend/app/services/ontology_generator.py`

- [x] **Neo4j entity summary flatten** — monkey-patch `Neo4jEntityNodeOperations.save/save_bulk`，LLM 返回嵌套 dict 时自动取 `.value` 扁平化，防 Neo4j TypeError
  - 文件：`backend/app/services/graphiti_client.py`

- [x] **Frontend 无 pending state 路由修复** — `/process/new` 访问时无上传状态，自动 `router.replace({name:'Home'})` 不再死循环
  - 文件：`frontend/src/views/MainView.vue`

- [x] **semaphore 100 → 30** — OASIS 模拟并发峰值降低，避免 GLM 限流雪崩
  - 文件：`backend/scripts/run_parallel_simulation.py`

### v0.3 完成（本次大版本前的全部更新）

#### 基础设施迁移
- [x] 从 Zep Cloud → 自托管 Graphiti + Neo4j（脱离外部 SaaS 依赖）
- [x] LLM 从 MiniMax M2.7 → 智谱 GLM-4-Flash（速度提升 2-5x）
- [x] Python 3.12 → 3.11.15（uv 管理 .venv-311，解决 camel-oasis 兼容性）
- [x] 服务器从 2C4G → 2C8G（解决 OOM 崩溃）
- [x] 加 4G swap → 总可用内存 ~13G
- [x] 配置 hf-mirror.com（解决 twhin-bert-base 下载卡死）

#### 性能优化
- [x] semaphore 30 → 100（每轮 2-3x 加速）
- [x] 找到 200 agents 内存/性能/统计置信度甜点
- [x] 双平台并行（Twitter + Reddit asyncio.gather）

#### 新功能
- [x] **Step 2 加速完成按钮**：profile 生成中可一键停止剩余、用已有进入下一步
- [x] **Manus 式过程回放界面**（核心 v0.3 交付）
  - 后端 `GET /api/simulation/:id/replay` 一次性返回全部回放数据
  - 前端 `/simulation/:id/replay` 三栏布局 + scrubber + 5 档播放速度
  - 工作流时间线 + 当前动作卡 + 滚动 feed + 聚合统计
  - 自动过滤历史 run 残留 actions

#### Bug 修复
- [x] **Backend SIGTERM 误杀模拟子进程 bug**：之前重启 Flask 会连带杀子进程，现已修复，可热更新后端代码不影响正在跑的模拟
- [x] CORS / Neo4j Query / DateTime 序列化等历史 bug

#### 文档与记忆系统
- [x] 部署信息全部归档到 M-flow（infra / lessons / services / credentials）
- [x] PRD.md / README.md 重写

### v0.4 待完成（路线图详见 §5）

- [ ] **国内平台抽象层**（P0）— 抖音 / 视频号 / 小红书 / 微博 / 公众号
- [ ] **Fork 模拟 + A/B 对比**（P1）— 模型复用与对比演化
- [ ] **多租户 SaaS 改造**（P2）— 子账户体系 + 计费 + 数据隔离
- [ ] **稳定性运维**（P3）— 子进程心跳 / 内存预算检查 / 自动清理

---

## 9. 关键文件索引

### 后端

| 路径 | 用途 |
|---|---|
| `backend/run.py` | Flask 入口 |
| `backend/app/__init__.py` | Flask 初始化（注意：v0.3 已移除 register_cleanup 的破坏性 signal handler） |
| `backend/app/api/graph.py` | 图谱构建 API |
| `backend/app/api/simulation.py` | 模拟 / prepare / start / stop / **replay**（新增 line ~2005） |
| `backend/app/api/report.py` | 报告生成 API |
| `backend/app/services/ontology_generator.py` | LLM 本体生成 |
| `backend/app/services/graph_builder.py` | Graphiti / Neo4j 图谱构建 |
| `backend/app/services/oasis_profile_generator.py` | Agent 画像生成（含加速完成 cancel_check 逻辑） |
| `backend/app/services/simulation_config_generator.py` | 模拟配置生成 |
| `backend/app/services/simulation_manager.py` | 模拟管理（含 accelerate flag） |
| `backend/app/services/simulation_runner.py` | 模拟运行（含 v0.3 register_cleanup 修复） |
| `backend/app/services/report_agent.py` | 报告 ReACT 生成 |
| `backend/scripts/run_parallel_simulation.py` | 双平台并行模拟脚本（semaphore=100） |

### 前端

| 路径 | 用途 |
|---|---|
| `frontend/src/router/index.js` | 路由（v0.3 新增 `/simulation/:id/replay`） |
| `frontend/src/api/simulation.js` | 模拟相关 API client |
| `frontend/src/views/SimulationReplayView.vue` | **v0.3 新增** Manus 式回放主界面 |
| `frontend/src/views/SimulationView.vue` | 模拟运行界面 |
| `frontend/src/views/SimulationRunView.vue` | 模拟启动界面 |
| `frontend/src/views/ReportView.vue` | 报告查看 |
| `frontend/src/components/Step2EnvSetup.vue` | Step 2 环境设置（v0.3 新增加速完成按钮） |

### 部署 / 运维

| 路径 | 说明 |
|---|---|
| `.env` | API Keys 与配置（智谱 / Neo4j / SiliconFlow / HF mirror） |
| `docker-compose.yml` | Neo4j 容器配置 |
| `~/.claude/projects/.../memory/` | M-flow 记忆系统索引（OpenClaw 内部） |

### 服务器（远程）

| 路径 | 说明 |
|---|---|
| `/opt/foresight/backend/` | 后端代码 |
| `/opt/foresight/backend/.venv-311/` | Python 3.11 虚拟环境（5.1G） |
| `/opt/foresight/backend/uploads/simulations/sim_<id>/` | 单次模拟数据目录 |
| `/opt/foresight/backend/logs/server.log` | Flask 日志 |
| `/opt/foresight/.env` | 服务器配置 |
| `/etc/nginx/sites-enabled/foresight-api` | Nginx 反代配置 |

---

## 10. 已知限制与边界

| 限制 | 说明 | 缓解策略 |
|---|---|---|
| Agent 数 ≤ 200（双平台 2C8G） | 超过会 OOM | 升级 4C16G / 单平台 / 拆分 batch |
| 国内平台未支持 | 当前只有 Twitter+Reddit | v0.4 P0 |
| 单租户 | 多客户共用一套数据 | v0.4 P2 |
| 子进程心跳缺失 | sim 挂了 state 仍是 running | v0.4 P3 |
| 报告生成 Token 消耗大 | 单次 80-150K | 优化 prompt / 缓存图谱搜索结果 |
| 重启 sim 需手动 reset state | 半死 state 阻塞下次启动 | v0.4 P3 加 force-restart 按钮 |

---

## 附录 A：v0.3 关键运维教训

1. **Python 版本约束必须 pre-flight 检查**：`requirements.txt` 改动后立刻验证 venv 兼容
2. **国内服务器装包必走腾讯云镜像**：`uv pip install --index-url http://mirrors.tencentyun.com/pypi/simple --trusted-host mirrors.tencentyun.com`
3. **HuggingFace 模型必配 `HF_ENDPOINT=https://hf-mirror.com`**：否则 OASIS 启动卡死
4. **遇到模拟卡死先看 simulation.log 最后 10 行**，不要先猜 LLM 慢
5. **8G 内存只能跑 200 agents 双平台**，503 会 OOM。要 503 双平台需升级 16G
6. **重启 Flask 不再杀子进程**（v0.3 修复后），可以安全热更新代码
7. **GLM-4-Flash 是 OASIS 场景的最优 LLM**：旗舰模型反而是反向优化（每次调用 2-5s 太慢）

## 附录 B：决策日志

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-04-13 | 从 Zep Cloud → Graphiti+Neo4j | 脱离外部依赖 |
| 2026-04-14 | LLM 切 GLM-4-Flash | MiniMax 速度不够 |
| 2026-04-14 | uv + Python 3.11 重建 venv | camel-oasis 不支持 3.12 |
| 2026-04-14 | 服务器升级 2C8G | 3.6G 跑不动 OASIS |
| 2026-04-14 | 配 hf-mirror.com | 服务器连不上 huggingface |
| 2026-04-15 | 修复 SIGTERM 误杀 bug | 热更新后端不再中断模拟 |
| 2026-04-15 | 200 agents 设为甜点 | 8G 容量 + 95% 置信度足够 |
| 2026-04-15 | 上线 Manus 式 replay UI | 给客户演示 + 复盘工具 |
| 2026-04-15 | v0.4 路线图：国内平台 + SaaS | 用户战略需求 |
| 2026-04-16 | v0.3.3 CustomGraphBuilder 替代 Graphiti | Graphiti 兼容性死循环，10+ 次 patch 仍无法稳定 |
| 2026-04-16 | 一键部署脚本 deploy.sh | 手动 scp 反复漏文件，accelerate 方法都没部署上 |
| 2026-04-16 | CDN SPA fallback 404→302 | coscmd 部署后前端所有子路由 404 |
| 2026-04-16 | 图谱构建并发化 (10 workers) | 串行太慢（10 分钟 → 2 分钟） |
| 2026-04-15 | v0.3.1 hotfix：7 个 bug 修复 | 第一次完整 E2E 跑通压力测试 |
| 2026-04-15 | LLM client 加指数退避重试 + 双 LLM fallback | GLM RPM 配额低，retry 不够兜底 |
| 2026-04-15 | Replay UI 重构为 Manus cinematic 风格 | 三栏分析面板对客户演示不够"沉浸" |
| 2026-04-15 | semaphore 100 → 30 | 高并发触发 GLM 限流雪崩 |

## 附录 C：Graphiti 弃用记录

v0.3.2 决定用自研 CustomGraphBuilder 替代 Graphiti。以下是尝试修复 Graphiti 兼容性的完整过程。

### 尝试过的 10 次 Patch

| # | 问题 | Patch 位置 | 结果 |
|---|---|---|---|
| 1 | Qwen 32B 32K context 超窗口 | ontology_generator MAX_TEXT=28000 | ✅ 但这不是主问题 |
| 2 | Neo4j TypeError 嵌套 dict | EntityNode.save monkey-patch | ❌ Graphiti 不走这条路径 |
| 3 | 同上 | bulk_utils.add_nodes_and_edges_bulk_tx | ❌ 也不走这条路径 |
| 4 | 同上 | neo4j AsyncSession.run driver 层 | ✅ 终于拦到了 |
| 5 | Qwen 累积上下文爆 60-82K | chunk_size 500→250 | ❌ 爆的是检索上下文不是 chunk |
| 6 | 同上 | 换 Qwen 72B（以为 128K） | ❌ SiliconFlow 72B 也是 32K |
| 7 | 同上 | 换智谱 GLM-4-Flash 128K | ❌ GLM 20015 "parameter invalid" |
| 8 | GLM reranker logprobs 不支持 | patch reranker.rank() | ✅ 但不是主路径 |
| 9 | GLM embedder 空 input | patch embedder.create_batch() | ✅ 但不是主路径 |
| 10 | GLM extract_nodes 全部 fail | 未找到根因 | ❌ 直接测能过、生产必挂 |

### 为什么自研是正确决策

1. **Graphiti 为 OpenAI 设计**：内部 4-5 次 LLM 调用路径各自有 OpenAI 特有参数（logprobs / structured output / json_schema），非 OpenAI provider 每条路径都是独立陷阱
2. **patch 层次太深**：至少 5 层（EntityNode / bulk_utils / driver / reranker / embedder），每层 fix 一个又冒下一个
3. **上下文累积不可控**：Graphiti 的 episode 检索机制会从已有图谱拉上下文，后续 episode prompt 越来越长，32K 模型必爆，128K 模型也不是免费的
4. **每 chunk 4-5 次 LLM 调用**：extract_nodes + dedupe_nodes + extract_edges + dedupe_edges + community_summary，成本和延迟 4-5x
5. **CustomGraphBuilder 只需 1 次调用/chunk**：直接 prompt → JSON → cypher MERGE，完全受控

### CustomGraphBuilder 架构

```
输入: 完整文档文本 + ontology 定义
  ↓
字符级切分 (250 chars, 50 overlap)
  ↓
ThreadPoolExecutor (10 workers 并发)
  ↓ 每个 worker:
  LLMClient.chat_json(extract prompt)  ← 一次调用，自带 retry + fallback
  ↓ 返回:
  {"entities": [...], "relationships": [...]}
  ↓
串行 MERGE 到 Neo4j (去重 by name + group_id)
  ↓
输出: {entities_count, edges_count, chunks_processed}
```

### 保留的 Graphiti 代码

`graphiti_client.py` 中的读取方法（`get_all_nodes / get_all_edges / get_node / get_node_edges`）仍然使用 Neo4j 直接查询，**不依赖 Graphiti 库**。`add_episode / add_episodes_batch` 保留但不再被主流水线调用。5 层 monkey-patch 保留作为安全网。

## 附录 D：部署流程

### 后端部署（最常用）

```bash
./scripts/deploy.sh              # rsync + restart Flask + health verify
./scripts/deploy.sh --no-restart  # 只同步代码不重启
```

### 前端部署

```bash
./scripts/deploy.sh --frontend    # vite build + coscmd upload + CDN purge
```

### 全量部署

```bash
./scripts/deploy.sh --full        # 后端 + 前端
```

### CDN SPA 配置（一次性）

```bash
tccli cdn UpdateDomainConfig --cli-unfold-argument \
  --Domain foresight.yizhou.chat \
  --ErrorPage.Switch on \
  --ErrorPage.PageRules.0.StatusCode 404 \
  --ErrorPage.PageRules.0.RedirectCode 302 \
  --ErrorPage.PageRules.0.RedirectUrl "https://foresight.yizhou.chat/index.html"
```

### COS 配置

- Bucket: `foresight-1317962478`
- Region: `ap-guangzhou`
- 凭证: `~/.cos.conf`（SecretId/SecretKey）
- 工具: `coscmd`（pip install）
