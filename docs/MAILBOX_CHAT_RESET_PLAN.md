# Mailbox Chat Reset Plan

## 1. 快速结论

当前项目已经偏离了最初想解决的问题。

真正要做的，不是继续强化 `parser + findings board + 大量状态面板`，而是回到用户真实的双终端协作方式，并把它产品化：

1. 页面主视图改成聊天室，而不是仪表盘。
2. `Executor` 和 `Reviewer` 的自然语言回复原样展示，不再从正文里硬解析语义。
3. 共享文件夹系统继续存在，但它的职责是 `mailbox + artifacts + current facts`，不是给前端做复杂语义解析。
4. 系统只保留最小状态：谁该回复、是否需要用户审批、当前属于计划阶段还是实施阶段。
5. 第一阶段采用“每轮新调用一次 CLI”的方式实现，不先做长期会话桥接。
6. 断电或重启后，新 agent 通过 `执行人手册 / 监督人手册 / current facts / mailbox` 快速恢复，不依赖隐藏 session 记忆。

一句话概括：

**回退为 chat-first、mailbox-driven、artifact-attached、minimal-state 的系统。**

## 2. 当前实现为什么跑偏

当前原型的主要偏移点有四个：

1. 前端主视图被做成了“状态机面板集合”，用户需要理解很多内部结构，阅读成本过高。
2. 后端过度依赖自然语言解析，尤其是对 reviewer 输出的 `decision / findings / severity` 解析。
3. 系统试图替 agent 理解对方的话，而不是把对话和产物原样呈现出来。
4. 计划阶段和实施阶段的展示被做得过重，遮蔽了最重要的交互：`谁刚刚说了什么，下一轮轮到谁`。

这些设计没有提升真实协作效率，反而让产品远离用户当前的手工工作流。

## 3. 这次回退后要保留什么

以下内容继续保留：

1. SQLite：继续作为最小元数据索引与审批记录存储。
2. 文件系统 artifacts：继续保存计划书、review、实现草稿、current facts 等可读文档。
3. Approval gate：继续保留计划审批、checkpoint 审批、最终审批。
4. CLI adapter：继续通过 `Codex CLI` 和 `Claude CLI` 进行本地调用。
5. Timeline / logs：继续保留，用于审计和回放，但不再成为主视图。

## 4. 这次回退后要拿掉什么

以下内容不再作为主路径：

1. 对 reviewer 正文进行强语义解析的主流程依赖。
2. 复杂的 blocker / concern / suggestion 前端主界面。
3. 以多面板 dashboard 为中心的信息架构。
4. 试图由系统替 agent 保存“私有记忆”的设计。
5. 把计划书解析结果直接当成执行步骤主视图的做法。

说明：

这不代表这些能力永远不存在，而是它们不应当作为当前版本的主干。

## 5. 目标产品形态

下一版产品的主形态如下：

1. 左侧是 `Rooms / Runs / 参与角色`。
2. 中间主区是聊天室消息流。
3. 消息分为四类：
   - 用户消息
   - Executor 消息
   - Reviewer 消息
   - System 消息
4. 每条消息可以挂附件：
   - `plan_v1.md`
   - `review_v1.md`
   - `current_facts.md`
   - `step_2_report.md`
5. 用户在输入框里通过 `@executor`、`@reviewer` 直接插话，模拟在真实终端里对某个 agent 说话。
6. 审批不是单独一个复杂页面，而是聊天流中的“待审批卡片”。
7. 计划阶段和执行阶段的差别，主要通过系统消息和附件类型体现，而不是靠重面板切换。

## 6. 核心设计原则

### 6.1 系统不理解正文，只路由正文

系统需要知道：

1. 这条消息是谁发的。
2. 这条消息发给谁。
3. 这条消息属于哪个 room / run。
4. 这条消息是否附带 artifact。
5. 当前是否卡在用户审批点。

系统不再负责：

1. 从正文里猜 block / concern / suggestion。
2. 从正文里猜“是不是允许下一步”。
3. 从正文里提取复杂结构化语义作为主流程推进依据。

### 6.2 项目事实落盘，不依赖隐藏记忆

系统不替 agent keep 私有记忆。

系统只保证以下事实始终存在且可恢复：

1. `执行人手册`
2. `监督人手册`
3. `current_facts.md`
4. `latest_approved_plan.md`
5. `mailbox/` 中的历史消息与附件

断电后，新 agent 通过阅读这些内容恢复工作状态。

### 6.3 第一阶段先不用长期会话

第一阶段不做“两个长期驻留 session 的桥接器”。

第一阶段采用：

1. 每轮新调用一次 CLI。
2. 每次调用时，把 `角色手册 + current facts + 最近 mailbox + 当前触发消息 + 相关 artifacts` 拼成上下文。
3. 让 agent 输出自然语言回复与附件。

这样可以最大化稳定性，并保留之后升级到长期 session 的空间。

## 7. 目标目录模型

建议新增或收口为如下目录结构：

```text
runtime/
  rooms/
    {room_id}/
      state.json
      manuals/
        executor_manual.md
        reviewer_manual.md
      shared/
        current_facts.md
        latest_approved_plan.md
        next_step.md
      mailbox/
        0001_user.md
        0002_executor.md
        0003_reviewer.md
      artifacts/
        plan/
        review/
        implementation/
        approvals/
```

说明：

1. `mailbox/` 主要保存消息副本与轮次关系。
2. `artifacts/` 保存正式文档。
3. `shared/` 保存恢复现场时必须先读的事实文档。
4. `manuals/` 保存角色说明，不把角色提示散落在代码里。

## 8. 最小数据库模型

SQLite 继续保留，但只保留最小元数据。

建议最终只需要这些核心表：

1. `rooms`
2. `runs`
3. `messages`
4. `artifacts`
5. `approvals`
6. `participants`

这些表解决的是索引、查询、审批、排序，不解决正文语义理解。

## 9. 详细实施步骤

### Step 1. 冻结当前原型并标记“回退方向”

目标：

1. 明确当前版本不再继续强化 dashboard-first 方向。
2. 把 parser-heavy 的路径降级为旧实验方案。

产出：

1. 文档说明当前回退决策。
2. 标记哪些前端/后端模块将在下一阶段被替换。

### Step 2. 收口领域模型

目标：

1. 把核心对象收口为 `room / run / message / artifact / approval / participant`。
2. 去掉把正文语义结构化后推进流程的依赖。

产出：

1. 新的消息模型。
2. 新的最小审批模型。
3. 新的 room/run 生命周期定义。

### Step 3. 重做 mailbox 协议

目标：

1. 每次 agent 回复都形成一条 message。
2. message 可以附带多个 artifact。
3. message 只需要极薄元数据，不再强行解析正文。

最小 envelope 字段：

1. `message_id`
2. `room_id`
3. `run_id`
4. `sender`
5. `recipient`
6. `kind`
7. `created_at`

### Step 4. 重写 CLI 触发层

目标：

1. 让系统像“替用户轮流去敲两个终端”。
2. 第一阶段保持每轮独立 CLI 调用。

每轮触发时，输入内容统一由以下部分构成：

1. 角色手册
2. 当前共享事实
3. 最近 mailbox 消息
4. 相关 artifact 路径
5. 当前动作要求

动作要求示例：

1. `请以执行人身份继续回应 reviewer 的最新意见。`
2. `请以监督人身份严格审查 executor 的最新回复，并说明是否允许进入下一步。`
3. `请先阅读 current_facts 和 latest_approved_plan，再继续当前轮次。`

### Step 5. 聊天室前端替换现有控制台

目标：

1. 前端主视图切换为聊天室。
2. 用户能直接看到谁说了什么、附件是什么、现在轮到谁。

页面结构：

1. 左侧：rooms / runs / 角色状态
2. 中间：消息流
3. 右侧或抽屉：当前附件、当前审批、历史 timeline

要求：

1. `Executor` 与 `Reviewer` 消息气泡明确区分。
2. `System` 消息只负责提示，不喧宾夺主。
3. Artifact 作为消息附件展开，而不是单独主导页面。

### Step 6. 把审批改成聊天流中的卡片

目标：

1. 计划审批、checkpoint、最终审批都变成消息流中的审批卡片。
2. 用户看到卡片就知道当前需要批什么。

审批卡片必须明确写出：

1. 当前审批对象是什么
2. 建议先看哪些附件
3. 批准后会发生什么
4. 驳回后会发生什么

### Step 7. 做重启恢复机制

目标：

1. 断电或进程重启后，新 agent 可以快速回到接近原状态。
2. 不依赖隐藏 session 记忆。

恢复步骤：

1. 新 agent 启动时先读角色手册。
2. 再读 `current_facts.md`。
3. 再读最近几轮 mailbox。
4. 再读当前动作要求。

系统要做的只是把这些入口组织好，而不是替 agent keep memory。

### Step 8. 用户直达干预能力

目标：

1. 用户可以在聊天室里随时 `@executor` 或 `@reviewer` 纠偏。
2. 这种插话直接进入 mailbox，并成为下一轮上下文的一部分。

要求：

1. 用户指令可以定向给单个角色。
2. 用户插话不会破坏现有审批 gate。
3. 系统要能区分“普通消息”和“需要立即路由的管理消息”。

### Step 9. 旧设计清理与迁移

目标：

1. 把当前 parser-heavy、dashboard-heavy 的实现降级或移除。
2. 保留仍然有用的运行时存储与 artifact 索引能力。

优先保留：

1. CLI adapters
2. SQLite repository 基础能力
3. artifact store
4. approval persistence

优先删减：

1. 强语义 review parser 主路径
2. 复杂 findings 面板主路径
3. 多面板状态机前端主入口

## 10. 第一阶段交付范围

第一阶段只做以下闭环：

1. 创建 room / run
2. 指定 executor / reviewer
3. 用户发送初始需求
4. Executor 产出 `plan_v1.md`
5. Reviewer 产出自然语言审核与 `review_v1.md`
6. 用户在聊天流中审批计划
7. Executor 按步骤实施
8. Reviewer 针对每一步给自然语言审核
9. checkpoint 和最终审批在聊天流中完成

第一阶段不做：

1. 长期 session 维持
2. 自动 findings 抽取主流程
3. 复杂 dashboard
4. 大规模并行多 agent

## 11. 验收标准

只要满足以下条件，就说明这次回退是成功的：

1. 用户进入页面后，第一眼看到的是消息流，而不是复杂状态面板。
2. 用户能清楚区分 `Executor`、`Reviewer`、`System`、`User` 四类消息。
3. 用户在任何时刻都知道“现在轮到谁”。
4. 计划书、review、实施报告都能作为附件直接查看。
5. 系统不再依赖正文语义解析来推进主流程。
6. 重启后，新 agent 可以通过手册和共享事实恢复协作。
7. 用户可以通过 `@executor` / `@reviewer` 直接纠偏，而不是切换外部终端。

## 12. 实施顺序建议

建议严格按以下顺序实施：

1. 先定数据模型和 mailbox 协议。
2. 再重写 CLI 触发层。
3. 再替换前端为聊天室。
4. 再把审批卡片接入聊天流。
5. 最后再清理旧 dashboard 和旧 parser 逻辑。

原因：

如果先改前端而不改后端协议，只会继续在错误的信息架构上打补丁。

## 13. 这份计划对应的最终方向

这不是“去掉所有系统化能力”，而是把系统职责收缩到正确的位置：

1. 系统负责路由、记录、审批、恢复。
2. agent 负责阅读、判断、写文档、互相审查。
3. 用户负责定方向、做审批、必要时直接纠偏。

下一版的系统本质上应当像：

**一个带共享邮箱、附件、审批卡片和角色手册的双 agent 聊天式工作台。**
