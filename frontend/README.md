# Frontend Control Console

前端不是为了把文件夹做成更漂亮的文件浏览器，而是为了给用户一个“项目当前真相”的控制台。

当前实际可运行的控制台重点展示：

- run 列表
- 当前 run 的状态、步骤和审批动作
- 计划审批时的 checkpoint 选择
- timeline、findings、artifacts、command history
- 最终审批和全程回看

当前目录里有两套前端表达：

- `frontend/site`：当前真实可运行的静态控制台，由 `backend/server.py` 直接托管，并调用 `/api/runs*` 等接口。
- `frontend/src`：React 版信息架构草图，用来表达组件形态和页面结构，目前还没有接入构建工具和真实数据源。

设计原则：

- 优先信息密度，不追求花哨设计
- 任何状态都要能追溯到原始产物
- 用户应该一眼看出“现在卡在哪”“为什么卡住”“下一步是谁”
- 计划审批和执行审批必须是显式动作，不做隐式跳转
