# Multi-Agent Collaboration Platform — 项目介绍

## 一句话概述

**~4000行代码、零依赖的多Agent协作编排平台** — 纯Python标准库实现，整个系统一下午就能读完。

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
| 后端代码 | **~2,100 行** Python | 7个模块，每个都能单独读完 |
| 前端代码 | **~1,860 行** 原生JS/CSS/HTML | 无框架、无构建步骤 |
| 总代码量 | **~4,000 行** | 整个可运行的系统 |
| 第三方依赖 | **0** | 纯Python标准库 + 原生浏览器API |
| 数据库表 | **3 张** | rooms, sessions, messages |
| API端点 | **12 个** | RESTful，全部JSON |
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
| `router.py` | 703 | 核心编排：轮次调度、自动循环、审批流、邮箱同步、中断处理 |
| `session_mgr.py` | 396 | CLI进程生命周期：启动、流式读取、超时、清理 |
| `server.py` | 350 | HTTP服务器：12个端点 + 工作区验证 + 静态文件服务 |
| `store.py` | 212 | SQLite CRUD：3张表，线程安全，WAL模式 |
| `scaffolder.py` | 170 | 工作区创建：邮箱文件、角色手册、恢复文档 |
| `templates.py` | 73 | 模版加载：纯字符串替换，无模版引擎 |
| `office_sync.py` | 223 | Star-Office-UI状态同步桥接（可选） |

---

## 三个核心设计亮点

### 1. 邮箱模式（Mailbox Pattern）+ 系统级同步

Agent之间不直接通信。每轮结束后，**系统自动**将Agent的输出同步到邮箱文件：

```
runtime/rooms/{room_id}/.local_agent_ops/agent_mailbox/
├── 执行人_给_监督人.txt     ← 系统同步执行人的最新输出
├── 监督人_给_执行人.txt     ← 系统同步监督人的最新输出
├── 共识状态.txt             ← 状态追踪
├── 待决问题.txt             ← 问题记录
└── 轮次记录.txt             ← 完整历史（系统每轮自动追加）
```

**为什么是系统写而不是Agent写？**

早期设计让Agent自己写邮箱文件，但在实际运行中遇到了CLI沙箱权限问题：
Agent的工作区（如 `D:\projects\my-app`）和邮箱目录（`runtime/rooms/...`）
是不同路径，CLI沙箱只授予工作区写权限，导致Agent无法写入邮箱。

解决方案：`_sync_mailbox()` 在每轮结束后由系统代写。这也符合Harness设计理念
——系统控制所有I/O，Agent专注于思考。

**设计优势：**
- **可审计**：所有沟通都是纯文本文件，`cat` 就能查看
- **可恢复**：Agent崩溃后从文件恢复上下文，不依赖内存
- **绕过沙箱**：系统级写入，不受CLI权限限制
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

### 2.5 工作区验证与动态切换

创建Room时，系统验证工作区目录的**存在性**和**写权限**（通过创建+删除临时文件测试）。
运行时支持通过 `POST /api/rooms/{id}/workspace` 动态切换工作区，切换时会：
- 验证新路径的有效性
- 检查Room是否正在工作中（忙碌时拒绝切换）
- 更新Session配置并发送系统消息通知Agent

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
| **工作区验证** | 创建/切换时验证目录存在+写权限，防止运行时路径错误 |
| **邮箱代写** | 系统级 `_sync_mailbox()` 绕过CLI沙箱限制，保证邮箱一致性 |
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
- **黑盒执行**：看不到Agent内部的工具调用和推理过程（Agent内部行为由CLI控制）
- **依赖外部CLI**：需要安装Claude Code或Codex CLI
- **单用户设计**：没有认证系统和多租户支持
- **轮询模式**：前端3秒刷新一次，不是WebSocket实时推送

---

## 快速体验

```bash
git clone https://github.com/f4dszz/multi-agent-collaboration.git
cd multi-agent-collaboration/backend
python server.py
# 打开 http://127.0.0.1:8765
```

---

*最后更新：2026-04-13*
