# 系统架构设计

## 1. 总体思路

系统采用本地优先的分层架构：

- `SQLite` 保存编排状态和元数据
- 文件系统保存 Markdown、JSON、日志等真实产物
- 后端编排器负责状态机、规则引擎和 adapter 调度
- 前端控制台负责展示阶段、产物、阻塞项、审批状态

这比“共享文件夹 + 人工通知”更稳定，也比“只存数据库 blob”更适合审阅。

## 2. 架构分层

### 2.1 Presentation Layer

前端页面的重点不是美化，而是把复杂协作压成可观察的面板：

- Run Dashboard
- Artifact Viewer
- Finding Board
- Approval Gate
- Timeline

### 2.2 Application Layer

后端应用服务负责：

- 创建项目和 run
- 加载 workflow 模板
- 调用 CLI adapter
- 推进状态机
- 写入 artifact 与 metadata
- 触发审批和验证逻辑

### 2.3 Domain Layer

核心模型包括：

- `WorkflowRun`
- `WorkflowPolicy`
- `Finding`
- `ArtifactRef`
- `RunState`

这里不依赖具体 Web 框架，以便测试和规则演化。

### 2.4 Infrastructure Layer

- SQLite Repository
- File-based Artifact Store
- Git/Diff Adapter
- CLI Agent Adapter
- Event Stream / WebSocket

## 3. 核心组件

### 3.1 Workflow Engine

负责定义和推进状态机，确保 agent 不能跳过关卡。

主要职责：

- 校验合法状态流转
- 统计 plan / implementation revision 次数
- 判断是否需要第三角色介入
- 控制人工审批关卡

### 3.2 Agent Adapter

适配不同 CLI agent 的调用方式。

建议接口统一为：

- `prepare_context(role, stage, project_path, artifacts)`
- `launch_task(command, timeout, env)`
- `capture_output()`
- `normalize_result()`

这样后端不会依赖某一个 CLI 的文本格式。

### 3.3 Artifact Store

文件目录建议如下：

```text
artifacts/
└── {project_slug}/
    └── {run_id}/
        ├── plan/
        ├── review/
        ├── response/
        ├── implementation/
        ├── verification/
        └── timeline/
```

保存原则：

- 可读内容优先 Markdown
- 结构化检测结果优先 JSON
- CLI 原始输出保留日志副本

### 3.4 Repository

SQLite 保存索引和关系。

建议表：

- `projects`
- `workflow_runs`
- `artifacts`
- `findings`
- `approvals`
- `timeline_events`

## 4. 状态机

### 4.1 状态定义

- `drafting_plan`
- `plan_review`
- `plan_revision`
- `awaiting_plan_approval`
- `implementing`
- `implementation_review`
- `verifying`
- `awaiting_final_approval`
- `completed`
- `blocked`

### 4.2 标准流转

```text
drafting_plan
  -> plan_review
  -> plan_revision
  -> plan_review
  -> awaiting_plan_approval
  -> implementing
  -> implementation_review
  -> verifying
  -> awaiting_final_approval
  -> completed
```

异常流转：

- 任一关键阶段可进入 `blocked`
- 验证失败会回到 `implementing`
- 计划或实现评审要求修订时，会回到对应修订阶段

### 4.3 第三角色触发规则

满足任一条件即可标记 `requires_verifier = true`：

- 计划修订轮次达到阈值
- 风险标签命中 `database / security / concurrency / architecture`
- Reviewer 标记为高风险 run
- 自动验证与人工结论冲突

## 5. 数据与文件的边界

### 5.1 为什么不用纯文档

纯文档的问题：

- 当前状态需要人工推断
- blocker 是否关闭无法快速查询
- 前端很难做统计和提醒
- 多轮 plan / review / response 之间的对应关系容易混乱

### 5.2 为什么不用纯数据库

纯数据库的问题：

- 计划和评审报告可读性差
- 复杂文本 diff 不自然
- 不利于用户直接打开原始产物审阅

### 5.3 混合存储原则

- SQLite 保存“关系”和“当前真相”
- 文件系统保存“正文”和“审计副本”

## 6. 前端信息架构

最小页面建议：

- `Project List`：项目与最近 run
- `Run Dashboard`：当前阶段、负责人、审批状态、倒计时
- `Artifact Workspace`：按轮次看 plan/review/response/verify
- `Finding Board`：查看 blocker、concern、suggestion 以及是否已解决
- `Approval Console`：用户批准、驳回、加批注

### 6.1 Run Dashboard 组件

- 阶段条
- 时间线
- 争议列表
- 产物列表
- 人工关卡卡片

## 7. 项目目录建议

```text
backend/
  app/
    api/
      contracts.py
    domain/
      models.py
      state_machine.py
    services/
      artifacts.py
      orchestrator.py
      repository.py
frontend/
  src/
    App.tsx
    pages/RunDetailPage.tsx
    types.ts
roles/
  executor.md
  reviewer.md
  verifier.md
  human_gate.md
workflows/
  default_local_workflow.json
tests/
  test_artifact_store.py
  test_repository.py
  test_state_machine.py
```

## 8. 可靠性设计

- 所有状态流转写入 `timeline_events`
- 任何自动阶段跳转前先持久化当前产物索引
- CLI adapter 必须记录原始输入摘要和输出摘要
- 失败任务保留 stderr/stdout 快照，便于复盘
- 人工审批决定与备注必须可审计

## 9. 后续演进顺序

### 第一阶段

- 先稳定状态机、artifact store、SQLite repository
- 用假数据或 mock adapter 驱动前端页面

### 第二阶段

- 接 Codex CLI / Claude Code CLI adapter
- 引入 WebSocket 事件推送
- 接 Git diff 聚合

### 第三阶段

- 支持多 workflow 模板
- 支持多项目并行
- 再评估是否升级到 Postgres 和多用户权限
