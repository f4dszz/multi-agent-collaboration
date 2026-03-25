# 测试策略与测试用例

## 1. 测试目标

重点验证三件事：

1. 工作流是否能阻止越权流转和跳过评审
2. 结构化元数据与文件产物是否能同时落地
3. 用户能否在关键节点获得正确的审批和状态反馈

## 2. 测试分层

### 2.1 单元测试

覆盖：

- 状态机流转
- 第三角色触发规则
- 产物目录创建和版本写入
- SQLite schema 初始化和基本 CRUD

### 2.2 集成测试

覆盖：

- 创建项目后发起 run
- 写入计划产物并推进到评审
- 记录 finding 后进入修订
- 人工批准后进入实施
- 验证失败后回退实施

### 2.3 手工验收测试

覆盖：

- 页面是否能在一个视图里看清全部关键状态
- 用户是否无需翻文档就能定位 blocker
- 用户是否能直接在审批关卡批准或驳回

## 3. 单元测试用例

### TC-U01 状态机默认流转

- 前置条件：新建 workflow run
- 步骤：提交计划 -> 评审通过 -> 用户批准 -> 提交实现 -> 实现评审通过 -> 验证通过 -> 用户最终批准
- 预期：run 最终为 `completed`

### TC-U02 计划评审要求修订

- 前置条件：run 已提交计划并进入 `plan_review`
- 步骤：Reviewer 返回 `revise`，并带一个 blocker
- 预期：run 进入 `plan_revision`

### TC-U03 计划修订回到评审

- 前置条件：run 在 `plan_revision`
- 步骤：Executor 提交修订并标记已响应 blocker
- 预期：run 回到 `plan_review`，finding 状态变为 `addressed`

### TC-U04 高风险标签触发第三角色

- 前置条件：run 在 `plan_review`
- 步骤：Reviewer 使用 `revise`，并附加风险标签 `security`
- 预期：`requires_verifier = true`

### TC-U05 实现评审不通过

- 前置条件：run 在 `implementation_review`
- 步骤：Reviewer 返回 `revise`
- 预期：run 回到 `implementing`

### TC-U06 验证失败回退

- 前置条件：run 在 `verifying`
- 步骤：Verifier 记录验证失败
- 预期：run 回到 `implementing`

### TC-U07 非法状态流转被阻止

- 前置条件：run 仍在 `drafting_plan`
- 步骤：直接调用最终审批
- 预期：抛出状态错误

## 4. 产物与仓储测试用例

### TC-S01 创建 run 目录结构

- 前置条件：空白 artifact 根目录
- 步骤：初始化 run 目录
- 预期：自动创建 `plan / review / response / implementation / verification / timeline`

### TC-S02 写入文本产物

- 前置条件：run 目录已存在
- 步骤：写入计划 Markdown
- 预期：文件存在，路径与 artifact metadata 一致

### TC-S03 SQLite schema 初始化

- 前置条件：空白数据库路径
- 步骤：执行 repository `initialize()`
- 预期：核心表全部存在

### TC-S04 项目与 run 持久化

- 前置条件：schema 已初始化
- 步骤：创建 project 和 run
- 预期：能查到 project slug、workflow_name 和初始 state

## 5. 前端验收测试用例

### TC-F01 运行仪表板可见性

- 步骤：打开 run 详情页
- 预期：能同时看到阶段、时间线、阻塞项、审批状态、产物列表

### TC-F02 争议定位

- 前置条件：存在多个 finding
- 步骤：筛选 `blocker`
- 预期：用户能快速看到未关闭 blocker 及其对应产物

### TC-F03 审批操作

- 前置条件：run 处于 `awaiting_plan_approval`
- 步骤：用户点击批准并附带备注
- 预期：状态推进到 `implementing`，审批记录入库

## 6. 失败与恢复测试

### TC-R01 CLI 任务超时

- 前置条件：agent adapter 超时
- 步骤：记录失败事件
- 预期：run 不应无声跳转，时间线存在 timeout 记录

### TC-R02 后端重启恢复

- 前置条件：run 已推进到中间阶段
- 步骤：服务重启并从 SQLite 重载 run
- 预期：前端可恢复显示准确阶段和 artifact 列表

### TC-R03 产物写入成功但状态更新失败

- 前置条件：artifact 已生成，数据库更新故障
- 步骤：触发恢复任务
- 预期：系统能识别未索引 artifact 并提示修复

## 7. 非功能测试建议

- 大项目 run 的时间线加载性能
- 大量 Markdown 产物的差异渲染性能
- 多轮评审情况下的查询性能
- 同时运行多个本地 agent 进程时的资源占用

## 8. 当前仓库已落地的自动化测试

当前自动化测试覆盖：

- 状态机关键流转
- 产物目录与写入
- SQLite schema 初始化与项目/run 基本持久化

后续接入真实 CLI adapter 后，应继续补集成测试和端到端测试。
