# Local Agent Workflow Orchestrator

一个本地优先的多代理协作编排器参考项目，用来约束 `Codex CLI`、`Claude Code CLI` 这类代理在复杂项目中的协作方式，减少单个长会话 agent 带来的方向漂移。

这个仓库目前交付的是一版可落地的架构骨架，重点包括：

- 产品架构说明：为什么不能继续靠文档邮箱和手动 trigger
- 系统架构说明：为什么采用 `SQLite + 文件产物库` 的混合模式
- 后端核心骨架：工作流状态机、产物存储、SQLite 元数据仓
- 前端信息架构骨架：用户如何实时看进展、看 diff、看争议点、做审批
- 测试样例：核心状态流转、产物写入、仓储初始化

## 核心结论

- 主流程采用 `Executor + Reviewer`
- 第三角色不是常驻“优化人”，而是按条件触发的 `Verifier / Judge`
- 用户不再翻文档，而是在统一面板中查看时间线、产物、差异、阻塞项和审批关卡
- 文档继续保留，但不再承担流程状态本身；流程真相由 SQLite 维护

## 目录

```text
.
├── README.md
├── backend
│   └── app
│       ├── api
│       ├── domain
│       └── services
├── docs
│   ├── PRODUCT_ARCHITECTURE.md
│   ├── SYSTEM_ARCHITECTURE.md
│   └── TEST_CASES.md
├── frontend
│   ├── README.md
│   └── src
├── roles
│   ├── executor.md
│   ├── reviewer.md
│   ├── verifier.md
│   └── human_gate.md
├── tests
└── workflows
    └── default_local_workflow.json
```

## 文档入口

- 产品说明见 [docs/PRODUCT_ARCHITECTURE.md](docs/PRODUCT_ARCHITECTURE.md)
- 系统设计见 [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md)
- 测试策略与测试用例见 [docs/TEST_CASES.md](docs/TEST_CASES.md)

## 运行测试

当前仓库中的测试只依赖 Python 标准库：

```powershell
python -m unittest discover -s tests -v
```

## 当前实现边界

这不是一版完整产品，而是一版克制的架构骨架。已经落地的内容主要用于验证三件事：

1. 工作流状态机能否强制计划评审、编码评审、验证和人工关卡。
2. 元数据和文档产物能否分层存储，而不是继续把一切都塞进共享文件夹。
3. UI 是否能围绕“阶段、争议、审批、差异”来构建，而不是把文档目录搬到网页上。

下一阶段才应该继续接入真实的 CLI adapter、WebSocket 推送和 Git diff 聚合。
