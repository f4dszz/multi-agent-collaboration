# Multi-Agent Collaboration Platform — 项目介绍

## 一句话概述

**2500行代码、零依赖的多Agent协作编排平台** — 纯Python标准库实现，整个系统一下午就能读完。

---

## 它解决什么问题

当你让两个AI Agent协作完成一个任务时，你需要一个"项目经理"：
- 谁先做？谁后做？
- 做完了通知谁？
- 出错了怎么重试？
- 什么时候该问人类？

这个平台就是这个项目经理。它**不思考**——只做人类项目经理做的事：建工作区、分配任务、传话、在关键节点问用户。

---

## 核心数据

| 指标 | 数值 | 说明 |
|------|------|------|
| 后端代码 | **1,482 行** Python | 7个模块，每个都能单独读完 |
| 前端代码 | **1,065 行** 原生JS/CSS/HTML | 无框架、无构建步骤 |
| 总代码量 | **~2,500 行** | 整个可运行的系统 |
| 第三方依赖 | **0** | 纯Python标准库 + 原生浏览器API |
| 数据库表 | **3 张** | rooms, sessions, messages |
| API端点 | **11 个** | RESTful，全部JSON |
| 模版文件 | **5 个** | 纯文本，`{variable}` 替换 |

---

## 架构设计

### 整体结构

```
用户 → 浏览器UI → HTTP API → Router（编排）
                                 ├→ SessionManager → CLI子进程（Agent执行）
                                 ├→ Store（SQLite持久化）
                                 ├→ Templates（提示词模版）
                                 ├→ Scaffolder（工作区初始化）
                                 └→ OfficeSyncBridge → Star-Office-UI（可选可视化）
```

### 模块职责

| 模块 | 行数 | 职责 |
|------|------|------|
| `router.py` | 531 | 核心编排：轮次调度、自动循环、审批流、中断处理 |
| `session_mgr.py` | 329 | CLI进程生命周期：启动、流式读取、超时、清理 |
| `server.py` | 257 | HTTP服务器：11个端点 + 静态文件服务 |
| `store.py` | 172 | SQLite CRUD：3张表，线程安全，WAL模式 |
| `scaffolder.py` | 135 | 工作区创建：邮箱文件、角色手册、恢复文档 |
| `templates.py` | 58 | 模版加载：纯字符串替换，无模版引擎 |
| `office_sync.py` | 200 | Star-Office-UI状态同步桥接（可选） |

---

## 三个核心设计亮点

### 1. 邮箱模式（Mailbox Pattern）

Agent之间不直接通信。每个Agent有自己的"发件箱"文件：

```
.local_agent_ops/agent_mailbox/
├── 执行人_给_监督人.txt     ← 执行人写，监督人读
├── 监督人_给_执行人.txt     ← 监督人写，执行人读
├── 共识状态.txt             ← 双方共同维护
├── 待决问题.txt             ← 问题追踪
└── 轮次记录.txt             ← 历史记录
```

系统从不替Agent写邮箱，只说"去看对方写了什么"。

**为什么这么做？**
- **可审计**：所有沟通就是.txt文件，人类可以直接打开查看
- **可恢复**：Agent崩溃后从文件恢复上下文，不依赖内存
- **解耦**：Agent不需要知道对方的实现细节

### 2. 编排与执行完全解耦

系统不关心Agent用什么LLM、怎么思考、用什么工具。它只控制两件事：
- **谁先说话**（轮次调度）
- **什么时候停**（审批/共识/错误检测）

```python
# 接入新的LLM CLI只需要：
# 1. 拼命令行参数
# 2. 写一个20行的 line_parser 解析其JSONL输出
# 3. 调用通用的 _run_stream()
```

当前支持 Claude Code CLI 和 Codex CLI，但架构上对任何CLI工具开放。

### 3. 人机协作光谱

不是"全自动"或"全手动"的二选一，而是一个连续的控制光谱：

```
手动逐步              半自动                    全自动
    ├─ 每步点按钮        ├─ 自动循环               ├─ Full-Auto
    ├─ 选择目标Agent     ├─ 共识时暂停             ├─ 最多20轮
    └─ 附加用户消息      └─ 失败3次暂停            └─ 随时可中断
```

用户可以在任意时刻：
- **Interrupt**：安全中断当前Agent（在检查点停止，不是强杀）
- **Intervene**：直接给Agent发消息（附加到下一轮模版中）
- **Approve/Reject**：控制流程走向

---

## 使用流程

```
1. 创建 Room
   └─ 指定工作区路径、选择Executor/Reviewer的Provider

2. Onboard
   └─ 系统给双方Agent发送角色手册，建立初始认知

3. 下发任务
   └─ 用户描述想让Executor做的事

4. 协作循环
   └─ Executor工作 → Reviewer审核 → 反馈 → 修改 → ...

5. 审批
   └─ Approve完成 / Reject继续修改
```

---

## 技术栈

```
后端:  Python标准库（http.server + sqlite3 + subprocess + threading）
前端:  原生HTML/CSS/JS（无框架、无构建步骤）
CLI:   Claude Code CLI / Codex CLI（通过subprocess + JSONL流式通信）
存储:  SQLite（WAL模式）+ 文件系统（邮箱文件）
UI:    深色主题，像素风格
```

**为什么零依赖？**
- 部署简单：有Python就能跑
- 理解容易：没有框架魔法
- 维护成本低：不会因为依赖升级而崩溃

---

## 状态机

```
onboarding → awaiting_task → working ⇄ awaiting_approval → completed
                                ↑              │
                                └──────────────┘ (reject)
```

每个状态都有对应的UI控件和权限控制：
- `working`：显示中断按钮，禁用审批
- `awaiting_approval`：启用Approve/Reject，禁用下一轮
- `completed`：显示新任务输入框

---

## 安全与容错

| 机制 | 说明 |
|------|------|
| **Per-Room锁** | 每个Room独立的threading.Lock，防止并发竞态 |
| **优雅中断** | Interrupt设置协作标志，在检查点停止，不在执行中途 |
| **自动重试** | 单轮失败最多重试2次 |
| **自动暂停** | 连续3轮失败自动暂停Full-Auto，等待用户介入 |
| **共识检测** | 扫描输出关键词（"无异议"/"approved"），自动暂停请求确认 |
| **进程清理** | Room删除时级联终止所有子进程 + 删除DB记录 + 清理文件 |
| **Session恢复** | 崩溃后Agent可从recovery文件快速重建上下文 |

---

## Star-Office-UI 集成（可选）

支持与 [Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI)（6.5k stars）集成，
在像素风办公室中可视化Agent工作状态：

- Executor和Reviewer作为访客Agent注册到办公室
- 实时推送工作状态（idle → writing → error）
- 心跳保活（120秒间隔，防止5分钟超时自动离线）
- 断线自动重连

```bash
# 在UI侧边栏点击 "🏢 Star-Office" 按钮一键连接
```

---

## 适合谁

### ✅ 适合
- 想**理解**多Agent系统底层原理的学习者（代码量小到能全部读完）
- 需要一个**可控的**双Agent协作环境的研究者（不是LangChain那种黑盒）
- 想在此基础上**扩展**自己Agent平台的开发者（架构清晰，模块解耦）
- 需要**快速搭建**Agent协作原型的团队（零依赖，clone即跑）

### ⚠️ 局限
- **不是Harness**：看不到Agent内部的工具调用和推理过程（正在开发中）
- **依赖外部CLI**：需要安装Claude Code或Codex CLI（API模式开发中）
- **单用户设计**：没有认证系统和多租户支持
- **轮询模式**：前端3秒刷新一次，不是WebSocket实时推送

---

## 演进方向

当前 `main` 分支是稳定的CLI模式。`feature/cli-to-api` 分支正在将系统从
**编排器（Orchestrator）** 进化为 **线束系统（Harness）**：

| 维度 | 现在（CLI模式） | 目标（Harness模式） |
|------|-----------------|---------------------|
| Agent执行 | CLI子进程（黑盒） | ReAct自主循环（可观测） |
| 工具调用 | Agent自行决定（不可见） | 每次经过系统（可控制、可记录） |
| 成功验证 | Reviewer主观判断 | 客观验证（测试通过？编译成功？） |
| LLM通信 | 通过CLI中转 | httpx直调API |
| 依赖要求 | Python + Node.js + CLI工具 | Python + API key |

---

## 快速体验

```bash
git clone https://github.com/f4dszz/multi-agent-collaboration.git
cd codex_project/backend
python server.py
# 打开 http://127.0.0.1:8765
```

---

*最后更新：2026-04-11*
