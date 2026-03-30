# Long Session Minimal Bridge Plan

## 1. 目标

把当前项目收口成一个轻量的双 Agent 工作台：

1. 用户在前端像聊天室一样和 `Executor`、`Reviewer` 交互。
2. `Executor` 和 `Reviewer` 是两个长期存活的 Agent CLI session。
3. 系统只负责桥接、展示、追踪、审批。
4. 正式工作文件由 Agent 自己写入共享文件夹。
5. 系统不解析 Agent 正文，不替 Agent 写 mailbox，不替 Agent 保存隐藏记忆。
6. `Reviewer` 默认把审查意见写入给 `Executor` 的 mailbox，不要求每一轮都生成单独的 `review.md`。

一句话概括：

**系统负责搭台和接线，Agent 负责思考、写文档、相互交接。**

## 2. 需要明确回退的方向

当前项目里需要明确回退的方向：

1. 回退 `dashboard-first` 的主界面方向。
2. 回退对自然语言正文做重解析的方向。
3. 回退“系统替 Agent 写 mailbox / handoff”的方向。
4. 回退“系统试图理解 review 结论并自动推进大部分流程”的方向。

这次方案里，正文只做展示，不做主语义驱动。

## 3. 职责边界

### 3.1 系统负责什么

系统只负责以下事情：

1. 初始化共享文件夹脚手架。
2. 建立并维护两个长期 session：
   - `Executor`
   - `Reviewer`
3. 记录谁绑定到哪个角色。
4. 把前端消息路由给正确的 Agent。
5. 把 Agent 的原始回复完整返回前端。
6. 发现并展示新生成的文档和附件。
7. 追踪 session 是否在线。
8. 在需要时显示最小审批卡片。

### 3.2 系统不负责什么

系统不再负责以下事情：

1. 不解析正文里的 `decision / findings / severity`。
2. 不把 Agent 回复二次转写进 mailbox。
3. 不替 Agent 保存“私有记忆”。
4. 不判断一段正文到底是 `review` 还是 `execution`。
5. 不把计划步骤自动转换成复杂状态机页面。

### 3.3 Agent 负责什么

`Executor` 和 `Reviewer` 自己负责：

1. 阅读各自的 onboarding 文档。
2. 阅读共享文件夹中的正式材料。
3. 在共享文件夹中写计划书、交接文档、状态总结。
4. 在当前 session 里给用户自然语言回复。
5. 按各自角色职责互相交接。

补充：

1. `Executor` 的主要输出默认进入 `artifacts/`。
2. `Reviewer` 的日常审查意见默认进入 `agent_mailbox/监督人_给_执行人.txt`。
3. 只有重大审查节点才要求 `Reviewer` 生成单独的正式审查文档。

## 4. 长期 Session 模式

这一版明确采用长期 session。

目标体验接近用户当前的手工流程：

1. `Executor` 像一个持续打开的 Codex 终端。
2. `Reviewer` 像一个持续打开的 Claude Code 终端。
3. 用户在前端发送 `@executor` 或 `@reviewer`，就像在对应终端里说话。
4. Agent 的回复按原样显示回前端。

系统这里做的是 `session bridge`，不是 `session brain`。

系统只关心：

1. 这个 session 还活着吗。
2. 这条消息该送进哪个 session。
3. 这个 session 输出了什么。

系统不接管它们的思考过程。

## 5. 共享文件夹结构

系统启动时只做一次脚手架初始化。

建议目录结构：

```text
runtime/
  workspaces/
    {workspace_id}/
      .local_agent_ops/
        onboarding/
          执行人手册.txt
          监督人手册.txt
        agent_mailbox/
          README.txt
          执行人_给_监督人.txt
          监督人_给_执行人.txt
          当前情况.txt
          交接记录.txt
      artifacts/
        plans/
        implementation/
        checkpoints/
        formal_reviews/
```

说明：

1. `.local_agent_ops/onboarding/` 是角色手册。
2. `.local_agent_ops/agent_mailbox/` 是 Agent 自己维护的共享协作区。
3. `执行人_给_监督人.txt` 和 `监督人_给_执行人.txt` 是固定的 who-to-whom 通信槽位。
4. `当前情况.txt` 保留当前有效的共享事实、未决问题、下一步建议和用户待确认项。
5. `交接记录.txt` 只保留轮次索引和交接摘要，不重复整份 mailbox 正文。
7. `artifacts/` 才是真正的正式成果物目录。
8. `formal_reviews/` 只保存关键节点的正式审查结论，不保存每一轮细碎意见。

关键点：

**mailbox 里的内容由 Agent 自己写，不由系统代写。**

这个结构比 `to_executor/`、`to_reviewer/` 更贴近真实协作：

1. 不是“系统目录”，而是“人和 Agent 一眼能看懂的协作桌面”。
2. 不是每条消息一个文件，而是每个方向一个固定通信位。
3. 共享事实和未决事项不分散，恢复时只需要先看一份 `当前情况.txt`。
4. `交接记录.txt` 只做“这一轮发生了什么”的短索引，不承担正文存储职责。

## 6. Agent 启动方式

当用户选定谁是 `Executor`、谁是 `Reviewer` 后，系统只给他们一次轻量启动提示。

### 6.1 给 Executor 的启动要求

系统只需要告诉它：

1. 你是执行人。
2. 请先阅读 `.local_agent_ops/onboarding/执行人手册.txt`。
3. 请阅读以下共享文件：
   - `.local_agent_ops/agent_mailbox/当前情况.txt`
   - `.local_agent_ops/agent_mailbox/交接记录.txt`
   - 相关正式 artifacts
4. 之后你需要：
   - 在当前会话里给用户自然语言汇报
   - 把正式成果和交接内容写到共享文件夹中供 Reviewer 阅读

### 6.2 给 Reviewer 的启动要求

系统只需要告诉它：

1. 你是监督人。
2. 请先阅读 `.local_agent_ops/onboarding/监督人手册.txt`。
3. 请阅读以下共享文件：
   - `.local_agent_ops/agent_mailbox/当前情况.txt`
   - `.local_agent_ops/agent_mailbox/交接记录.txt`
   - 相关正式 artifacts
4. 之后你需要：
   - 在当前会话里给用户自然语言汇报
   - 把对 Executor 的审查意见默认写入 `.local_agent_ops/agent_mailbox/监督人_给_执行人.txt`
   - 只有在关键审查节点再额外写正式审查文档

## 7. 聊天式前端

前端主视图改成聊天式工作台。

### 7.1 主视图组成

1. 左侧：
   - workspace / run 列表
   - `Executor` / `Reviewer` 在线状态
2. 中间：
   - 聊天消息流
3. 右侧或抽屉：
   - 最新附件
   - 当前审批卡片
   - 共享文件入口

### 7.2 消息类型

只保留四类消息：

1. 用户消息
2. Executor 消息
3. Reviewer 消息
4. System 消息

这里的 `System` 只做提示，不解释正文。

### 7.3 Reviewer 在前端怎么呈现

`Reviewer` 的前端回复不需要是完整正式报告。

更合适的形态是：

1. 在前端给用户一个简化版结论或 findings 摘要。
2. 把详细可执行意见写进给 `Executor` 的 mailbox。
3. 只有关键节点再生成独立 `formal review` 文档。

这样用户可以快速看懂，而共享目录不会堆满大量 `review_v17.md` 之类的碎片文档。

## 8. 最小审批模型

审批仍然保留，但只保留最少的三个节点：

1. 计划审批
2. 关键 checkpoint 审批
3. 最终审批

审批以聊天流中的卡片形式出现，不单独做复杂审批后台。

审批卡片只需要说明：

1. 当前要批什么。
2. 建议先看哪些附件。
3. 同意后会发生什么。
4. 驳回后建议由谁继续处理。

## 9. 典型工作流

### 9.1 初始化

1. 系统创建 workspace。
2. 系统创建共享目录脚手架。
3. 系统写入 onboarding 模板和 mailbox 模板。
4. 用户指定 Executor 和 Reviewer。
5. 系统分别启动两个长期 session。

### 9.2 计划阶段

1. 用户提出需求。
2. 系统把消息发给 Executor。
3. Executor 产出：
   - 前端可见的自然语言回复
   - `artifacts/plans/plan_v1.md`
   - 写入 `.local_agent_ops/agent_mailbox/执行人_给_监督人.txt` 的交接内容
4. 用户和系统都能看到 Executor 的回复和附件。
5. 系统或用户再触发 Reviewer。
6. Reviewer 阅读共享文件，产出：
   - 前端可见的自然语言回复
   - 写入 `.local_agent_ops/agent_mailbox/监督人_给_执行人.txt` 的审查意见 / handoff 文档
   - 只有在关键审查节点才写单独的正式 review artifact
7. 用户查看计划书和审核意见后决定是否插话或审批。

### 9.3 执行阶段

1. Executor 按计划推进。
2. 每到关键节点，Executor 写阶段汇报和相关附件。
3. Reviewer 基于共享文件继续审查。
4. Reviewer 默认把执行反馈写入 `.local_agent_ops/agent_mailbox/监督人_给_执行人.txt`，并在前端回复中给出精简结论。
5. 只有在需要形成正式留档时，才生成单独 review 文档。
6. 用户可随时 `@executor` / `@reviewer` 中断、调整、补充要求。

## 10. 重启恢复

这套方案不依赖系统保留 Agent 的隐藏记忆。

如果断电或 session 中断：

1. 系统重新拉起新的 Agent session。
2. 系统要求新 Agent 先读 onboarding 文档。
3. 系统要求新 Agent 再读：
   - `.local_agent_ops/agent_mailbox/当前情况.txt`
   - `.local_agent_ops/agent_mailbox/交接记录.txt`
   - 最新附件
   - 对向 mailbox 文件中的最近有效交接内容
4. 然后再恢复对话。

恢复能力来自共享文件，不来自黑盒 session 记忆。

## 11. 最小数据库模型

SQLite 继续保留，但只做索引和展示支持。

建议只保留最小对象：

1. `workspaces`
2. `participants`
3. `sessions`
4. `messages`
5. `artifacts`
6. `approvals`

这些表只回答：

1. 谁是谁
2. 哪个 session 是否在线
3. 哪条消息是谁说的
4. 哪些附件已出现
5. 哪个审批还没处理

数据库不负责正文理解。

## 12. 实施步骤

### Step 1. 重写计划与边界

目标：

1. 明确长期 session 是主路径。
2. 明确系统不代写 mailbox。
3. 明确 Agent 自写 handoff 文档。
4. 明确 `Reviewer` 默认写 mailbox，不要求每轮单独 review 文档。
5. 明确 mailbox 采用“谁给谁”的固定槽位，而不是 `to_executor/` 这种系统味很重的目录。
6. 明确共享摘要收口为 `当前情况.txt`，而不是拆成多个弱相关文件。

产出：

1. 本计划文档
2. 对旧计划的替代说明

### Step 2. 收口后端核心对象

目标：

1. 后端只保留 `workspace / session / message / artifact / approval / participant`
2. 去掉重 parser 的主路径依赖

产出：

1. 新的数据模型
2. 新的 session 管理接口

### Step 3. 实现长期 session bridge

目标：

1. 启动两个长期 Agent CLI session
2. 支持把消息送入指定 session
3. 支持实时接收指定 session 的输出
4. 支持 session 存活检测和异常恢复

产出：

1. session manager
2. executor / reviewer 绑定
3. 消息路由层

### Step 4. 实现共享文件夹脚手架

目标：

1. 创建 `.local_agent_ops/onboarding/` 模板
2. 创建 `.local_agent_ops/agent_mailbox/` 模板
3. 创建 `artifacts/` 基础目录

产出：

1. workspace initializer
2. 默认模板文件

### Step 5. 改前端为聊天式工作台

目标：

1. 前端主界面改成聊天流
2. 原样展示 Agent 回复
3. 附件作为消息附件挂载
4. 审批改成消息卡片

产出：

1. 新聊天页面
2. session 状态展示
3. 附件抽屉或侧栏

### Step 6. 实现用户直达干预

目标：

1. 用户可以 `@executor`
2. 用户可以 `@reviewer`
3. 用户可以在中途插入调整意见

产出：

1. 定向消息输入
2. 中断后重新路由能力

### Step 7. 做恢复与重连

目标：

1. session 断开后可重建
2. 新 Agent 可通过共享文件快速进入状态

产出：

1. restart flow
2. reconnect flow

## 13. 验收标准

只要满足以下条件，就说明这条路线正确：

1. 用户第一眼看到的是聊天流，不是 dashboard。
2. 用户可以明确区分 Executor、Reviewer、User、System 四类消息。
3. Agent 回复按原样展示，不依赖正文解析。
4. 计划书、阶段汇报、handoff 文档由 Agent 自己写入共享目录。
5. `Reviewer` 不需要每轮都生成新的 `review.md`。
6. 系统不再代写 mailbox。
7. 用户可以通过 `@executor` / `@reviewer` 直接插话。
8. session 断开后，新 session 可以通过 onboarding 和共享文件恢复到可继续工作的状态。
9. mailbox 采用“谁给谁”的固定槽位，而不是一堆零散消息文件。
10. `当前情况.txt` 同时承载共享事实、未决事项和下一步建议，避免文件过多。
11. `交接记录.txt` 只做轮次索引和交接摘要，不重复 mailbox 正文。

## 14. 一句话结论

下一版系统不应该像“理解一切的编排器”，而应该像：

**一个带聊天界面、`.local_agent_ops/agent_mailbox`、最小审批卡片和双长期 Agent session 的轻量工作台。**
