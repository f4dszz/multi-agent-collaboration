# Local Agent Workflow Orchestrator

一个本地优先的多代理协作编排器参考项目，用来约束 `Codex CLI`、`Claude Code CLI` 这类代理在复杂项目中的协作方式，减少单个长会话 agent 带来的方向漂移。

这个仓库当前已经落地到一个可运行的本地控制台原型，重点包括：

- 用户提交需求后，`Executor + Reviewer` 先完成计划讨论
- 计划进入人工审批，用户可以决定哪些步骤需要 checkpoint 审批，或者一次性执行到最终审批
- 批准后系统按计划步骤推进，并把 timeline、steps、approvals、artifacts、command history 保留下来
- 运行态采用 `SQLite + 文件产物库`：SQLite 保存结构化真相，Markdown 产物继续给人看
- 静态前端控制台可以查看 run 列表、计划、步骤、审批和命令记录

## 核心结论

- 主流程采用 `Executor + Reviewer`
- 第三角色不是常驻“优化人”，而是按条件触发的 `Verifier / Judge`
- 用户不再翻文档，而是在统一面板中查看时间线、步骤、产物、阻塞项和审批关卡
- 文档仍然保留，给人审阅；流程真相由 SQLite 维护
- Markdown 和结构化数据不是二选一，而是双轨：Markdown 给人看，SQLite/结构化字段给系统推进状态

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

## 主流程

当前 demo 的主流程是：

1. 用户提交需求，创建一个 run。
2. `Executor` 起草计划，`Reviewer` 审核计划；若需要，系统自动进行若干轮计划修订。
3. 计划进入 `awaiting_plan_approval`，用户查看计划并勾选哪些步骤需要 checkpoint 审批。
4. 用户批准计划后，系统按步骤执行。
5. 如果某一步被标记为 checkpoint，执行完该步后停在 `awaiting_checkpoint_approval`。
6. 全部步骤完成后进入 `awaiting_final_approval`。
7. 用户最终批准后，run 进入 `completed`。

## 运行测试

当前仓库中的测试只依赖 Python 标准库：

```powershell
python -m unittest discover -s tests -v
```

## 运行 Demo

当前仓库里真正可运行的一体化 Demo 是：

- 后端 API：`backend/server.py`
- 静态前端：`frontend/site`

推荐直接从仓库根目录启动：

```powershell
python -m backend.server
```

然后在浏览器打开：

```text
http://127.0.0.1:8765/
```

这会同时提供：

- 前端控制台页面
- `/api/health`
- `/api/providers`
- `/api/runs`
- `/api/runs/{run_id}`
- `/api/runs/{run_id}/continue`
- `/api/runs/{run_id}/plan-approval`
- `/api/runs/{run_id}/checkpoint-approval`
- `/api/runs/{run_id}/final-approval`
- `/api/last-run`
- `/api/reviews/repo`

## SQLite 与产物

运行态数据在：

- SQLite：`runtime/orchestrator.db`
- 运行快照：`runtime/runs/*.json`
- Markdown 产物：`runtime/artifacts/<project>/<run_id>/`
- 这些都属于本地运行产物，只用于调试与回放，不提交到 Git

SQLite 里目前最重要的表有：

- `workflow_runs`：run 的主状态
- `run_contexts`：任务、workspace、provider、审批模式、当前步骤索引
- `execution_steps`：每一步的标题、详情、状态、是否需要审批
- `approvals`：计划审批、checkpoint 审批、最终审批
- `timeline_events`：时间线
- `findings`：review 产出的结构化问题
- `artifacts`：Markdown 产物索引
- `command_results`：CLI 调用记录

如果你要直接看表，我现在的查看方式通常是：

```powershell
@'
import sqlite3
conn = sqlite3.connect("runtime/orchestrator.db")
for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(row[0])
'@ | python -
```

或者查询某张表：

```powershell
@'
import sqlite3
conn = sqlite3.connect("runtime/orchestrator.db")
conn.row_factory = sqlite3.Row
for row in conn.execute("SELECT run_id, state FROM workflow_runs ORDER BY run_id DESC LIMIT 20"):
    print(dict(row))
'@ | python -
```

如果要可视化，最直接的是：

- `DB Browser for SQLite`
- VS Code 的 SQLite 扩展
- JetBrains/DataGrip 这类数据库工具

是否要把 SQLite 直接暴露给最终用户看，要看场景。对普通使用者，前端控制台里的 run/steps/approvals/timeline 已经更合适；数据库更偏开发者排障视角。

## 当前实现边界

当前版本已经不是纯文档骨架，但也还不是最终产品。当前边界主要有：

1. 执行推进仍然是同步 HTTP 调用，不是后台 job queue。
2. 当前前端是静态站点，没有 WebSocket 推送。
3. Reviewer 对执行步骤的反馈目前会把 run 阻塞下来，还没有更细的“自动返工若干轮”策略。
4. `frontend/src` 仍然只是 React 草图；真实交付前端是 `frontend/site`。

下一阶段更应该做的是任务后台化、实时推送、diff 聚合，以及更细的 checkpoint/审批策略，而不是再扩展一堆自由聊天式 agent。
