# Codex Project - 轻量多Agent邮箱路由系统

本地多Agent协作编排平台。系统只做"人肉中继"做的事：建文件夹、发模版触发词、等agent做完、通知对方、关键节点问用户。

## 快速开始

### 前置要求

- Python 3.10+
- Claude Code CLI（已安装并登录）
- Node.js（Claude Code依赖）

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd codex_project

# 无需安装依赖 — 纯标准库，零第三方包
```

### 启动

```bash
cd backend
python server.py
# Server running at http://127.0.0.1:8765
```

浏览器打开 http://127.0.0.1:8765 即可使用。

## 使用流程

```
1. 点击 [+] 创建 Room
   - 填写 Room ID、Workspace（真实存在的项目路径）
   - 选择 Executor/Reviewer 的 Provider（claude 或 codex）

2. 点击 [Onboard]
   - 系统给双方agent发送角色手册
   - 执行人和监督人分别了解自己的职责
   - 流式输出：可以实时看到agent的思考过程

3. 输入任务
   - Onboard完成后弹出任务输入框
   - 输入你想让执行人做的事情，回车发送
   - 执行人收到任务后开始工作

4. 协作循环
   - [Next Round]: 手动触发下一轮（executor → reviewer 交替）
   - [▶ Full-Auto]: 全自动模式，executor ↔ reviewer 持续循环
   - [⏸ Pause]: 暂停全自动模式
   - 底部输入框: 直接给指定agent发消息（用户干预）

5. 审批
   - [Approve]: 确认当前阶段完成
   - [Reject]: 驳回，要求继续修改
```

## 架构

### 设计原则

```
系统做的事                系统不做的事
────────                 ────────
建文件夹结构              组装上下文
发模版触发词              解析agent输出
等agent做完              代agent写邮箱
通知另一个agent           维护隐式记忆
关键节点问用户            复杂状态机
展示对话流
```

Agent有自己的持久session和记忆。系统只发一句简单的模版提示词（如"去检查对方的回复，严格分析"），不注入上下文。

### 技术栈

- **后端**: Python标准库（http.server + sqlite3 + subprocess + threading）
- **前端**: 原生HTML/CSS/JS（无框架、无构建）
- **CLI通信**: Claude Code CLI（`--output-format stream-json --verbose`，流式输出）
- **持久session**: Claude Code的`--session-id` + `--resume`，agent保持完整记忆
- **存储**: SQLite（3张表：rooms, sessions, messages）+ 文件系统（邮箱文件）

### 目录结构

```
codex_project/
├── backend/
│   ├── server.py           # HTTP Server（8个端点）
│   └── app/
│       ├── scaffolder.py   # Room文件夹结构创建
│       ├── templates.py    # 模版加载和渲染
│       ├── session_mgr.py  # CLI session管理（流式Popen）
│       ├── router.py       # 消息路由（后台线程 + Full-Auto循环）
│       └── store.py        # SQLite存储（rooms/sessions/messages）
├── frontend/
│   └── site/
│       ├── index.html      # 单页应用
│       ├── styles.css      # 深色主题
│       └── app.js          # Chat UI + 轮询 + Markdown渲染
├── templates/              # 5个提示词模版
│   ├── onboarding.txt      # 首次发角色手册
│   ├── trigger_execute.txt # 让执行人开始工作
│   ├── trigger_review.txt  # 让监督人审核
│   ├── trigger_respond.txt # 让执行人回应反馈
│   └── trigger_recover.txt # Session恢复
├── docs/                   # 文档
└── tests/                  # 测试
```

### 邮箱文件结构（每个Room自动生成）

```
runtime/rooms/{room_id}/.local_agent_ops/
├── agent_mailbox/
│   ├── README.txt                    # 使用说明
│   ├── {执行人}_给_{监督人}.txt       # 执行人→监督人 固定槽位
│   ├── {监督人}_给_{执行人}.txt       # 监督人→执行人 固定槽位
│   ├── 共识状态.txt                  # 双方共识
│   ├── 待决问题.txt                  # 问题追踪
│   └── 轮次记录.txt                  # 轮次历史
├── onboarding/                       # 角色手册
└── recovery/                         # Session恢复文档
```

### API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/rooms` | 列出所有Room |
| POST | `/api/rooms` | 创建Room（脚手架 + onboarding） |
| GET | `/api/rooms/{id}` | Room详情 + 消息流 + 邮箱文件 |
| POST | `/api/rooms/{id}/next` | 触发下一轮（onboard/auto/executor/reviewer） |
| POST | `/api/rooms/{id}/task` | 下发任务给执行人 |
| POST | `/api/rooms/{id}/auto` | 开启/停止Full-Auto模式 |
| POST | `/api/rooms/{id}/approve` | 审批/驳回/用户干预 |

### 前端界面

```
┌──────────┬──────────────────────────────┬─────────────┐
│ Room列表  │       聊天消息流               │  邮箱文件    │
│          │                              │  查看器      │
│ [Room 1] │  系统: 已完成onboarding       │             │
│ [Room 2] │  执行人: [流式输出思考过程]     │  执行人邮箱  │
│          │  监督人: [审核结果]            │  监督人邮箱  │
│          │  系统: 等待用户操作            │  共识状态    │
│          │                              │  待决问题    │
│          │ [Onboard] [Next] [Auto] ...  │  轮次记录    │
│          │ [任务输入框 / 直接干预输入框]   │             │
└──────────┴──────────────────────────────┴─────────────┘
```

特性：
- 消息支持Markdown渲染（标题、加粗、代码块、列表）
- 流式输出：agent思考过程实时展示，带打字光标动画
- 邮箱文件展开/折叠状态记忆（轮询刷新不丢失）
- Full-Auto模式：executor ↔ reviewer自动循环，Pause一键暂停

## 状态流转

```
onboarding → awaiting_task → working ⇄ awaiting_approval → completed
                                ↑              │
                                └──────────────┘ (用户驳回)
```

- **onboarding**: 给双方agent发角色手册
- **awaiting_task**: 等用户输入第一个任务
- **working**: executor/reviewer轮流工作中
- **awaiting_approval**: 等用户审批
- **completed**: 全部完成
