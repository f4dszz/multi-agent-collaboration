# Codex Project - 多Agent协作编排平台

轻量级多Agent协作编排平台，正在从CLI wrapper架构演进为**自主循环Agent + Harness系统**。

## 当前状态

### `main` 分支 — 稳定版（CLI模式）
- Executor/Reviewer 双agent协作
- 通过 Claude Code CLI / Codex CLI 驱动agent
- Lightweight UI + 可选 Star-Office-UI 可视化监控
- Full-Auto模式、审批流、安全中断

### `feature/cli-to-api` 分支 — 开发中（Harness模式）
- **目标**：去掉CLI依赖，构建完整Harness系统
- Agent通过LLM API直接对话（httpx，无subprocess）
- ReAct自主循环（思考→工具调用→观察→再思考）
- 每次工具调用都经过系统——可观测、可控制、可记录
- 客观验证能力（跑测试、编译检查、diff审计）
- 只需API key即可运行

## 快速开始（main分支）

### 前置要求

- **Python 3.10+** — 纯标准库，零第三方依赖
- **Node.js 18+** — Claude Code CLI的运行时
- **Claude Code CLI** — 安装并登录完成

```bash
# 验证Claude Code CLI是否可用
claude --version

# 如果未安装
npm install -g @anthropic-ai/claude-code

# 如果未登录
claude auth login
```

### 启动

```bash
cd backend
python server.py
# Server running at http://127.0.0.1:8765
```

浏览器打开 http://127.0.0.1:8765 即可使用。

### Star-Office-UI 可视化（可选）

系统支持与 [Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI) 集成，
在像素风办公室中可视化agent工作状态。

```bash
# 启动 Star-Office-UI（需单独克隆和安装）
cd Star-Office-UI && python backend/app.py
# 在我们的UI侧边栏点击"Star-Office"按钮连接
```

## 使用流程

```
1. 创建 Room — 填写 Room ID、Workspace、选择 Provider
2. Onboard — 系统给双方agent发送角色手册
3. 下发任务 — 输入任务描述，回车发送
4. 协作循环 — executor ↔ reviewer 轮流工作
5. Full-Auto — 一键全自动循环，共识时自动暂停
6. 审批 — Approve 完成 / Reject 继续修改
```

## 架构

### 当前架构（main分支）

```
User → Frontend → HTTP API → Router (编排)
                                ├→ SessionManager → subprocess(CLI) → [黑盒]
                                ├→ Store (SQLite)
                                └→ OfficeSyncBridge → Star-Office-UI
```

### 目标架构（feature/cli-to-api分支）

```
User → Frontend → HTTP API → Router (编排)
                                ├→ Agent (ReAct循环)
                                │    ├→ Provider (httpx → Claude/OpenAI API)
                                │    └→ Tools (file_ops, shell, search, verify)
                                │         ↑ 每次调用都经过系统：可观测、可控制
                                ├→ Store (SQLite + tool_calls表)
                                └→ OfficeSyncBridge → Star-Office-UI
```

### 核心特性

| 特性 | 说明 |
|------|------|
| **统一消息发送** | Send = Next Round + 用户消息，agent走完整轮次流程 |
| **智能 Target** | 自动默认选对方agent，可手动覆盖 |
| **安全中断** | 在检查点优雅停止，不会跳到下一agent |
| **重试容错** | 失败自动重试2次，连续3轮失败暂停并提示用户 |
| **共识检测** | Full-Auto模式下，审核通过时自动暂停等待确认 |
| **流式输出** | agent思考过程实时展示 |
| **Star-Office集成** | 可选的像素风办公室可视化监控 |

### 目录结构

```
codex_project/
├── backend/
│   ├── server.py           # HTTP Server
│   └── app/
│       ├── router.py       # 消息路由 + Full-Auto循环
│       ├── session_mgr.py  # CLI session管理（将被替换）
│       ├── store.py        # SQLite存储
│       ├── scaffolder.py   # Room文件夹结构创建
│       ├── templates.py    # 模版加载和渲染
│       └── office_sync.py  # Star-Office-UI同步桥接
├── frontend/
│   └── site/
│       ├── index.html      # 单页应用
│       ├── styles.css      # 深色主题
│       └── app.js          # Chat UI + 轮询
├── templates/              # 5个提示词模版
├── docs/                   # 文档
└── tests/                  # 测试
```

### API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/rooms` | 列出所有Room |
| POST | `/api/rooms` | 创建Room |
| GET | `/api/rooms/{id}` | Room详情 + 消息流 + 邮箱文件 |
| DELETE | `/api/rooms/{id}` | 删除Room |
| POST | `/api/rooms/{id}/next` | 触发下一轮 |
| POST | `/api/rooms/{id}/task` | 下发任务 |
| POST | `/api/rooms/{id}/auto` | 开启/停止Full-Auto |
| POST | `/api/rooms/{id}/approve` | 审批/驳回/干预 |
| POST | `/api/rooms/{id}/interrupt` | 中断当前agent |
| POST | `/api/office-sync` | 连接/断开Star-Office |

## 状态流转

```
onboarding → awaiting_task → working ⇄ awaiting_approval → completed
                                ↑              │
                                └──────────────┘ (reject)
```

## License

MIT
