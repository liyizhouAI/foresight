# Foresight 先见之明 — 产品需求文档 (PRD)

## 1. 产品概述

Foresight（先见之明）是一个基于知识图谱和 LLM 的社交媒体舆情模拟平台。用户上传文档资料，系统自动构建知识图谱、生成虚拟 Agent 画像，并模拟社交媒体上的传播与互动行为，最终生成分析报告。

**核心价值**：在事件发生前预判舆论走向，帮助品牌、政府、机构提前制定应对策略。

**上游项目**：基于 [MiroFish](https://github.com/666ghj/MiroFish) v0.1.2 二次开发。

---

## 2. 目标用户

| 用户类型 | 使用场景 |
|----------|----------|
| 品牌公关团队 | 新品发布前预判舆论反应 |
| 政府舆情分析师 | 政策出台前模拟民意 |
| 内容创作者 | 预测爆款视频的传播路径 |
| 研究人员 | 社交网络传播行为研究 |

---

## 3. 系统架构

```
用户浏览器
  │
  ├── 前端 (Vue 3 + Vite)
  │     部署: 腾讯云 COS + CDN
  │     域名: foresight.yizhou.chat
  │
  └── 后端 (Flask + Python)
        端口: 5001
        │
        ├── LLM API (MiniMax M2.7 Highspeed)
        │     用途: 本体生成、画像生成、配置生成、报告生成
        │
        └── Zep Cloud API
              用途: 知识图谱存储、搜索、记忆更新
```

---

## 4. 核心功能流程（5 步流水线）

### Step 1: 图谱构建

**输入**: 用户上传文档（PDF/MD/TXT）+ 模拟需求描述

**流程**:
1. 文档解析 → 文本提取
2. LLM 分析文档 → 生成本体（10 个实体类型 + 6-10 个关系类型）
3. 文本分块 → 批量导入 Zep → 构建知识图谱
4. 返回图谱可视化（节点 + 边）

**API 端点**:
- `POST /api/graph/ontology/generate` — 本体生成
- `POST /api/graph/build` — 图谱构建
- `GET /api/graph/task/<task_id>` — 构建进度查询

**Token 消耗**:
| 服务 | 小文档 (10 实体) | 大文档 (50 实体) |
|------|------------------|------------------|
| LLM (本体生成) | 3K-8K | 5K-12K |
| Zep (图谱构建) | 5K-10K | 20K-50K |

### Step 2: 环境配置

**输入**: 已构建的知识图谱

**流程**:
1. 从 Zep 读取图谱实体和关系
2. 按实体类型筛选，为每个实体生成 Agent 画像（LLM）
3. 生成模拟配置：时间线、事件、Agent 活动参数、平台配置

**API 端点**:
- `POST /api/simulation/prepare` — 准备模拟环境

**Token 消耗**:
| 服务 | 小规模 (10 实体) | 大规模 (50 实体) |
|------|------------------|------------------|
| LLM (画像生成) | 20K-40K | 50K-100K |
| LLM (配置生成) | 20K-35K | 40K-50K |
| Zep (实体读取) | 1K-2K | 5K-10K |

### Step 3: 模拟运行

**输入**: Agent 画像 + 模拟配置

**流程**:
1. 创建虚拟社交平台环境
2. Agent 按配置执行社交行为（发帖、评论、转发、点赞等）
3. 实时记录互动日志
4. 可选：将 Agent 行为写回 Zep 图谱（记忆更新）

**API 端点**:
- `POST /api/simulation/run` — 启动模拟
- `GET /api/simulation/status/<sim_id>` — 查询状态
- `GET /api/simulation/history` — 历史记录

**Token 消耗**:
| 服务 | 说明 |
|------|------|
| Zep (记忆更新，可选) | 每个 Agent 动作 100-300 tokens，大规模模拟可达 1M+ |

### Step 4: 报告生成

**输入**: 模拟结果 + 知识图谱

**流程**:
1. LLM 规划报告大纲（5 个章节）
2. 每个章节使用 ReACT 循环（推理→工具调用→生成）
3. 工具调用包括：图谱搜索（InsightForge/Panorama）、节点详情查询
4. 最终输出结构化分析报告

**API 端点**:
- `POST /api/report/generate` — 生成报告

**Token 消耗**:
| 服务 | 小规模 | 大规模 |
|------|--------|--------|
| LLM (ReACT 多轮) | 50K-80K | 100K-150K |
| Zep (图谱搜索) | 5K-10K | 10K-20K |

> 报告生成是整个流水线中**Token 消耗最大**的环节。

### Step 5: 交互问答

**输入**: 用户问题

**流程**:
1. 用户自由提问
2. 系统结合图谱搜索 + LLM 回答

**API 端点**:
- `POST /api/report/chat` — 实时问答

**Token 消耗**: 每条消息 2K-4K tokens (LLM + Zep)

---

## 5. Token 消耗总览

### 单次完整流水线估算

| 阶段 | 主要 API | 10 实体 | 50 实体 |
|------|----------|---------|---------|
| 图谱构建 | LLM + Zep | 8K-18K | 25K-62K |
| 环境配置 | LLM + Zep | 41K-77K | 95K-160K |
| 模拟运行 | Zep (可选) | 0-100K | 0-1M+ |
| 报告生成 | LLM + Zep | 55K-90K | 110K-170K |
| **合计 (不含模拟记忆)** | | **~100K-185K** | **~230K-392K** |

### API 费用构成

| 外部服务 | 用途 | 计费方式 |
|----------|------|----------|
| **MiniMax M2.7 Highspeed** | 所有 LLM 推理（本体/画像/配置/报告/问答） | 按 token 计费 |
| **Zep Cloud** | 知识图谱（存储/搜索/记忆更新） | 按 API 调用计费 |

---

## 6. 技术栈

### 前端
| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | 3.x | UI 框架 |
| Vite | 7.x | 构建工具 |
| D3.js / Force Graph | - | 图谱可视化 |

### 后端
| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.x | 运行时 |
| Flask | - | Web 框架 |
| OpenAI SDK | - | LLM 客户端（兼容 MiniMax） |
| zep-cloud | 3.13.0 | Zep 知识图谱 SDK |

### 部署
| 组件 | 平台 | 说明 |
|------|------|------|
| 前端静态文件 | 腾讯云 COS + CDN | foresight.yizhou.chat |
| SSL 证书 | Let's Encrypt | 通过 acme.sh 签发 |
| 后端 API | 待部署 | 需要云服务器运行 Flask |

---

## 7. 配置项

```env
# LLM 配置
LLM_API_KEY=<MiniMax API Key>
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_MODEL_NAME=MiniMax-M2.5

# Zep 配置
ZEP_API_KEY=<Zep Cloud API Key>

# 服务端口
FLASK_PORT=5001
```

---

## 8. 当前状态与待办

### 已完成
- [x] 前端 UI（Vue 3，支持明暗主题）
- [x] 品牌迁移（MiroFish → Foresight 先见之明）
- [x] 前端部署（腾讯云 COS + CDN + HTTPS）
- [x] Dark Mode 全屏响应式布局
- [x] 国际化支持（中/英）

### 待完成
- [ ] **后端云部署**：当前后端只能在本地运行（localhost:5001），需部署到腾讯云 CVM 或轻量服务器
- [ ] **前端 API 地址配置**：设置 `VITE_API_BASE_URL` 指向云端后端
- [ ] **图谱生成功能验证**：端到端测试完整流水线
- [ ] **模拟结果持久化**：当前模拟结果存在内存中，需接入数据库
- [ ] **用户认证**：多用户场景下的身份管理

---

## 9. 关键文件索引

| 路径 | 用途 |
|------|------|
| `frontend/src/api/index.js` | API 客户端配置（baseURL） |
| `frontend/src/views/Process.vue` | 图谱构建主界面 |
| `frontend/src/views/SimulationView.vue` | 模拟运行界面 |
| `frontend/src/views/ReportView.vue` | 报告查看界面 |
| `backend/run.py` | 后端入口 |
| `backend/app/api/graph.py` | 图谱相关 API 端点 |
| `backend/app/api/simulation.py` | 模拟相关 API 端点 |
| `backend/app/api/report.py` | 报告相关 API 端点 |
| `backend/app/services/ontology_generator.py` | 本体生成服务（LLM） |
| `backend/app/services/graph_builder.py` | 图谱构建服务（Zep） |
| `backend/app/services/oasis_profile_generator.py` | Agent 画像生成（LLM + Zep） |
| `backend/app/services/simulation_config_generator.py` | 模拟配置生成（LLM） |
| `backend/app/services/report_agent.py` | 报告生成（ReACT，LLM + Zep） |
| `backend/app/utils/llm_client.py` | LLM 客户端封装 |
| `.env` | API Keys 和配置 |
