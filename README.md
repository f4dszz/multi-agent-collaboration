# Multi-Agent Collaboration Platform

零依赖、~4000行代码的多Agent协作编排平台。让两个AI Agent（执行人 + 监督人）在你的项目上协作完成任务。

## 它解决什么问题

当你需要让AI Agent写代码并希望有另一个Agent来审查时，你面对的核心问题是**编排**：

- 谁先做？做完了通知谁？
- 出错了怎么重试？什么时候该暂停问人类？
- Agent的沟通记录能不能像文件一样直接打开看？

这个平台就是这个"项目经理"。它**不思考**——只负责搭台、接线、传话、在关键节点等人类拍板。

## 快速开始

### 前置要求

- **Python 3.10+**（纯标准库，无需 `pip install`）
- **Claude Code CLI**（通过 `npm install -g @anthropic-ai/claude-code` 安装，需登录）

### 3步启动

```bash
git clone https://github.com/f4dszz/multi-agent-collaboration.git
cd multi-agent-collaboration/backend
python server.py
```

打开 http://127.0.0.1:8765 → 创建 Room → 设定工作区路径 → 下发任务 → 双Agent开始协作。

## 使用流程

```
1. 创建 Room     设定工作区路径（必须是真实存在的项目目录）、选择Provider
2. Onboard       系统给执行人和监督人发送角色手册，建立初始认知
3. 下发任务       描述你想让执行人做什么
4. 协作循环       执行人工作 → 监督人审核 → 反馈 → 修改 → ...
5. Full-Auto      一键全自动循环，达成共识时自动暂停等确认
6. 审批           Approve 完成 / Reject 继续修改 / Intervene 直接干预
```

## 核心特性

| 特性 | 说明 |
|------|------|
| **零依赖** | 纯Python标准库 + 原生HTML/CSS/JS，有Python就能跑 |
| **邮箱模式** | Agent间通过.txt文件通信，人类可直接打开审计 |
| **系统级邮箱同步** | 系统自动将Agent输出写入邮箱文件，绕过CLI沙箱限制 |
| **工作区验证** | 创建Room时验证目录存在+写权限，运行时可切换工作区 |
| **Full-Auto** | 一键自动循环，共识时自动暂停，最多20轮，随时可中断 |
| **安全中断** | 在检查点优雅停止，不会在执行中途强杀 |
| **重试容错** | 单轮失败自动重试2次，连续3轮失败暂停等待用户 |
| **流式输出** | Agent思考过程实时展示在聊天界面 |

## 架构

```
用户 → 浏览器UI → HTTP API → Router（编排引擎）
                                ├→ SessionManager → CLI子进程 → Agent
                                ├→ Store（SQLite持久化）
                                ├→ Scaffolder（工作区初始化 + 邮箱文件）
                                ├→ _sync_mailbox()（系统级邮箱写入代理）
                                └→ OfficeSyncBridge → Star-Office-UI（可选）
```

### 邮箱模式（Mailbox Pattern）

Agent之间不直接通信。系统在每轮结束后自动将Agent的输出同步到邮箱文件：

```
runtime/rooms/{room_id}/.local_agent_ops/agent_mailbox/
├── 执行人_给_监督人.txt     ← 执行人的最新输出
├── 监督人_给_执行人.txt     ← 监督人的最新输出
├── 共识状态.txt             ← 状态追踪
├── 待决问题.txt             ← 问题记录
└── 轮次记录.txt             ← 完整历史（系统自动追加）
```

**为什么这么做？**
- **可审计**：所有沟通都是纯文本文件，`cat` 就能查看
- **可恢复**：Agent崩溃后从文件重建上下文，不依赖内存状态
- **绕过沙箱**：系统级写入，不受CLI沙箱权限限制

### 目录结构

```
multi-agent-collaboration/
├── backend/
│   ├── server.py              # HTTP Server + 工作区验证
│   └── app/
│       ├── router.py          # 编排引擎（轮次调度、自动循环、审批、邮箱同步）
│       ├── session_mgr.py     # CLI进程管理（启动、流式读取、超时、清理）
│       ├── store.py           # SQLite存储（rooms/sessions/messages）
│       ├── scaffolder.py      # 工作区初始化 + 邮箱文件创建
│       ├── templates.py       # 提示词模版加载
│       └── office_sync.py     # Star-Office-UI同步桥接（可选）
├── frontend/site/
│   ├── index.html             # 单页应用
│   ├── styles.css             # 深色主题
│   ├── app.js                 # 聊天UI + 状态轮询
│   └── game.js                # Phaser.js像素办公室（可选）
├── templates/                 # 5个提示词模版（纯文本 + 变量替换）
├── roles/                     # Agent角色定义
├── tests/                     # 测试
└── docs/                      # 架构文档
```

### API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/rooms` | 列出所有Room |
| POST | `/api/rooms` | 创建Room（含工作区验证） |
| GET | `/api/rooms/{id}` | Room详情 + 消息 + 邮箱文件内容 |
| DELETE | `/api/rooms/{id}` | 删除Room（级联清理进程+文件） |
| POST | `/api/rooms/{id}/workspace` | 切换工作区 |
| POST | `/api/rooms/{id}/next` | 触发下一轮 |
| POST | `/api/rooms/{id}/task` | 下发任务 |
| POST | `/api/rooms/{id}/auto` | 开启/停止Full-Auto |
| POST | `/api/rooms/{id}/approve` | 审批/驳回/干预 |
| POST | `/api/rooms/{id}/interrupt` | 安全中断当前Agent |
| POST | `/api/office-sync` | 连接/断开Star-Office-UI |

## 状态机

```
onboarding → awaiting_task → working ⇄ awaiting_approval → completed
                                ↑              │
                                └──────────────┘ (reject)
```

## 技术栈

| 层 | 技术 | 依赖 |
|----|------|------|
| 后端 | Python标准库（http.server + sqlite3 + subprocess + threading） | 无 |
| 前端 | 原生HTML/CSS/JS + Phaser.js（可选） | 无构建步骤 |
| Agent | Claude Code CLI / Codex CLI（通过subprocess + JSONL流式通信） | npm |
| 存储 | SQLite（WAL模式）+ 文件系统（邮箱） | 无 |

## 详细文档

- [平台架构介绍](docs/platform-introduction.md) — 设计理念、模块详解、适用场景

## License

MIT
