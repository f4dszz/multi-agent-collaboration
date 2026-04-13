# 旅游计划 Agent App 设计方案

> 版本: v1.5
> 日期: 2026-04-09
> 作者: 执行人
> 状态: **终稿** — 执行人-监督人共识达成 (2026-04-09)
> 修订历史:
>   - v1.5 (2026-04-09): 处理监督人轮次1审核意见：统一角色命名为"执行人/审核人"（Ch4、Ch8、Ch10同步收敛）；修正修订历史章节编号错误；标准化共识状态字面量
>   - v1.4 (2026-04-09): 补写第十章"执行人-审核人协作流程"（v1.3遗漏）；原第十章总结顺延为第十一章
>   - v1.3 (2026-04-08): 闭合第9.2节所有待决问题；补充异常场景处理策略
>   - v1.2 (2026-04-07): 处理监督人轮次1审核意见：收敛版本表述、消解需求与MVP边界冲突、统一并行/串行表述

---

## 一、需求概述

### 1.1 用户场景

用户通过自然语言描述旅行意图，系统自动解析、规划并输出一份可执行的旅行方案。

**典型输入示例**：
> "我想在2026年10月1日从上海出发去伦敦旅游，大概7-10天"

**期望输出**：

| 输出项 | MVP阶段 | Phase 2（API集成后） |
|--------|---------|---------------------|
| 每日行程安排 | ✅ 完整规划 | ✅ 同左 |
| 交通方案 | ✅ 方向性建议（推荐航线/方式，无具体航班号和票价） | ✅ 含具体航班和实时票价 |
| 住宿推荐 | ✅ 区域和类型建议（无具体酒店价格） | ✅ 含具体酒店和实时价格 |
| 景点/活动安排 | ✅ 完整规划 | ✅ 同左 |
| 预算总览 | ⚠️ 按预算档的区间粗估（非实时报价，见5.3节） | ✅ 基于实时API的精确预算 |
| 协助订票 | ❌ 不支持 | ✅ 跳转订票链接 |

> **MVP边界说明**：MVP阶段所有涉及实时价格的输出均为"按预算档的区间粗估"，明确标注"仅作粗估，非实时报价"。具体价格、航班号、订票链接等依赖实时数据的内容为Phase 2能力。

### 1.2 核心流程

```
用户输入 → 入口Agent解析 → 制定计划 → 分发子任务 → 各Agent按Phase执行（MVP串行，目标架构Phase内可并行） → 汇总 → 输出完整方案
```

---

## 二、系统架构

### 2.1 架构总览

```
                         ┌─────────────────────┐
                         │      用户界面        │
                         │  (Chat / Web UI)     │
                         └─────────┬───────────┘
                                   │ 自然语言输入
                                   ▼
                         ┌─────────────────────┐
                         │   入口Agent (Router) │
                         │   - 意图解析         │
                         │   - 要素提取         │
                         │   - 计划制定         │
                         │   - 任务分发         │
                         │   - 结果汇总         │
                         └─────────┬───────────┘
                                   │ 分发子任务
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
           ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
           │  交通Agent    │ │  行程Agent    │ │  住宿Agent    │
           │  - 航班查询   │ │  - 路线规划   │ │  - 酒店查询   │
           │  - 火车查询   │ │  - 景点安排   │ │  - 比价推荐   │
           │  - 比价推荐   │ │  - 时间分配   │ │  - 区域建议   │
           └──────────────┘ └──────────────┘ └──────────────┘
                    │              │              │
                    └──────────────┼──────────────┘
                                   ▼
                         ┌─────────────────────┐
                         │   汇总 & 输出        │
                         │   完整旅行方案       │
                         └─────────────────────┘
```

### 2.2 与现有Codex平台的关系

本方案**复用Codex平台的基础设施**，并在其之上构建旅游领域的Agent App。

**现有架构约束分析**：
- 当前Router (`router.py`) 是固定双角色（executor/reviewer）轮转模型，`Turn = Literal["executor", "reviewer"]`
- `create_session()` 接口签名为 `(role, provider, workspace)`，无 `room_id` 参数
- `_do_round()` 和 `_auto_loop()` 硬编码了双角色切换逻辑
- 邮箱快照 (`_room_snapshot()`) 只读取 `*.txt` 文件
- 模板上下文 (`get_room_context()`) 只暴露固定的收件箱/发件箱/共识文件

**因此，旅游Agent App不能简单"扩展"Router，需要新增独立的任务编排层**：

| 层次 | 现有Codex | 旅游Agent App | 改造类型 |
|------|-----------|---------------|----------|
| 通信 | 邮箱文件系统（*.txt） | 复用txt邮箱，Agent间通过文本文件交换结果 | 复用 |
| 调度 | Router（双角色轮转） | **新增 TravelOrchestrator**（多角色DAG调度） | **新增模块** |
| 会话 | Session Manager | 复用，但需适配多Agent场景 | 小幅扩展 |
| 持久化 | SQLite 3表 | 新增 sub_tasks 表 | 扩展 |
| 上下文 | get_room_context（固定字段） | 扩展支持动态子Agent文件列表 | 扩展 |
| 快照 | _room_snapshot（*.txt） | 扩展支持 *.txt + 汇总方案.txt | 小幅扩展 |
| UI | Chat界面 | 扩展，增加子任务进度可视化 | 扩展 |

---

## 三、Agent 详细设计

### 3.1 入口Agent (Entry Agent / Coordinator)

**职责**：接收用户请求，解析意图，制定计划，分发任务，汇总结果。

**工作流程**：

```
1. 接收用户自然语言输入
2. 提取关键要素（结构化）
3. 判断缺失要素 → 追问用户补充
4. 制定执行计划（确定需要哪些子Agent）
5. 按依赖顺序分发任务
6. 收集各Agent结果
7. 汇总输出完整方案
```

**要素提取模板**：

```json
{
  "origin": "出发地",
  "destination": "目的地",
  "departure_date": "出发日期",
  "duration_range": "旅行天数范围（如'7-10天'），用户未给精确值时保留区间",
  "return_date": "返回日期（仅当用户明确给出时填写，否则为null）",
  "travelers": "旅行人数及构成（成人/儿童）",
  "budget": "预算范围（可选）",
  "transport_preference": "交通偏好（飞机/火车/自驾）",
  "accommodation_preference": "住宿偏好（酒店星级/民宿/青旅）",
  "interest_tags": ["文化历史", "自然风光", "美食", "购物", "冒险运动"],
  "special_requirements": "特殊需求（签证、无障碍、饮食限制等）"
}
```

**追问策略**：
- 必填要素缺失时主动追问（出发地、目的地、日期）
- **天数/返程确认**：当用户给出的是天数区间（如"7-10天"）而非精确返程日期时，入口Agent必须先提出默认假设（如"建议按8天7晚规划"）并请用户确认，确认后才将`duration_range`收敛为确定值
- 可选要素缺失时提供合理默认值（如预算=中等，住宿=3-4星酒店）
- 一次追问尽量覆盖所有缺失项，避免多轮追问

**任务分发决策逻辑**：

```python
def plan_agents(extracted_info):
    agents_needed = []

    # 交通Agent — 始终需要（除非用户已有交通方案）
    if not extracted_info.get("transport_booked"):
        agents_needed.append("transport_agent")

    # 行程Agent — 始终需要
    agents_needed.append("itinerary_agent")

    # 住宿Agent — 始终需要（除非当日往返）
    if extracted_info["duration_days"] > 0:
        agents_needed.append("accommodation_agent")

    # 签证Agent — 跨国旅行时需要
    if is_international(extracted_info["origin"], extracted_info["destination"]):
        agents_needed.append("visa_agent")

    return agents_needed
```

**执行顺序与依赖**：

> **依赖环消解说明**：v1.0中住宿Agent的输入依赖行程Agent的"区域推荐"，行程Agent又依赖住宿Agent的"住宿位置"，形成循环依赖。
> 解决方案：由入口Agent在Phase 0完成"区域预规划"，为住宿和行程提供统一的区域假设，打破循环。

**目标架构**（Phase内可并行，Phase间串行）：

```
Phase 0（入口Agent独立完成）：
  └── 区域预规划 → 根据目的地和用户兴趣，确定推荐住宿区域
      例：伦敦 + 博物馆兴趣 → 推荐住Bloomsbury/South Kensington区域

Phase 1（目标架构：可并行，无相互依赖）：
  ├── 签证Agent（如需要）→ 签证要求清单（待人工核验）
  ├── 交通Agent → 交通方式推荐、路线规划
  └── 住宿Agent → 基于入口Agent的区域假设，推荐住宿

Phase 2（依赖Phase 1结果，串行）：
  └── 行程Agent → 基于出发/返程日期 + 住宿区域 + 交通方式规划每日行程
      （MVP：按"到达日/完整天/返程日"粗粒度规划，不依赖实际航班时刻）
      （Phase 2：基于真实航班到达/离开时间精排首末日行程）

Phase 3：
  └── 入口Agent汇总 → 输出完整方案
```

**MVP实现策略**（全程串行）：

> MVP阶段所有Phase均串行执行（Phase 0 → 签证Agent → 交通Agent → 住宿Agent → 行程Agent → 汇总），不实现Phase 1内的并行调度。Phase 2迭代时再升级TravelOrchestrator支持Phase内并行。
>
> 选择串行的理由：降低TravelOrchestrator首版开发复杂度，先跑通端到端流程验证架构设计。

**依赖关系DAG（无环）**：
```
入口Agent(区域预规划)
    ├──→ 签证Agent
    ├──→ 交通Agent
    └──→ 住宿Agent（接收区域假设作为输入）
              │
    交通Agent ─┤
              ▼
         行程Agent（接收交通方式 + 住宿区域；MVP按粗粒度日期规划，Phase 2按实际时刻精排）
              │
              ▼
         入口Agent(汇总)
```

---

### 3.2 交通Agent (Transport Agent)

**职责**：查询和推荐交通方案。

**输入**：
- 出发地、目的地
- 出发日期、返回日期
- 人数
- 交通偏好
- 预算范围

**MVP阶段输出**（不含具体航班号、价格、订票链接）：

```
===== 交通方案推荐 =====
状态: 待人工核验

--- 去程建议 ---
推荐方式: 直飞航班
推荐航线: 上海浦东(PVG) → 伦敦希思罗(LHR)
推荐航司: 运营该航线的航空公司包括[待查]
预估飞行时间: 约11-13小时
⚠️ 具体航班号、时刻和价格需通过航空公司官网或OTA平台查询确认

--- 回程建议 ---
推荐航线: 伦敦希思罗(LHR) → 上海浦东(PVG)
⚠️ 同上，需实际查询

--- 当地交通建议 ---
推荐方式: 伦敦公共交通（地铁/公交）
建议购买: Oyster Card 或 Contactless支付
覆盖范围: Zone 1-2基本覆盖主要景点
⚠️ 具体票价以伦敦交通局(TfL)官网为准

--- 待核验清单 ---
□ 查询实际航班和票价（推荐：航空公司官网、携程、飞猪）
□ 确认护照有效期满足要求
□ 购买合适的旅行保险
```

**Tools**（Phase 2 API集成后生效）：
- `search_flights(origin, dest, date, passengers)` — 航班搜索（需对接Amadeus/Skyscanner API）
- `search_trains(origin, dest, date)` — 火车搜索（需对接TrainLine API）
- `get_local_transport_info(city)` — 当地交通信息
- `compare_prices(options)` — 比价

> **MVP阶段说明**：上述Tools在MVP阶段不调用真实API。交通Agent基于LLM知识给出**方向性建议**（推荐航线、推荐方式、大致飞行时长），但**禁止输出具体航班号、票价、出发/到达时刻和订票链接**。所有涉及价格和时刻的信息标记为"待人工核验"。行程Agent在MVP阶段不以交通Agent的具体时刻为输入，而是按"到达日/完整天/返程日"粗粒度规划（见3.4节）。

---

### 3.3 住宿Agent (Accommodation Agent)

**职责**：查询和推荐住宿方案。

**输入**：
- 目的地城市
- 入住/退房日期
- 人数及房间需求
- 住宿偏好（星级、类型）
- 预算范围
- 推荐住宿区域（由入口Agent在Phase 0预规划提供，不依赖行程Agent）

**MVP阶段输出**（不含具体酒店价格和预订链接）：

```
===== 住宿方案推荐 =====
状态: 待人工核验

--- 推荐住宿区域 ---
区域: [来自入口Agent预规划，如Bloomsbury]
选择理由: 靠近大英博物馆等核心景点，交通便利

--- 住宿类型建议 ---
经济型: 连锁快捷酒店（如Premier Inn、Travelodge品牌）
中档型: 3-4星商务酒店
舒适型: 精品酒店或4-5星酒店

⚠️ 具体酒店名称、价格和可用性需通过Booking.com/Hotels.com等平台查询
⚠️ 10月为旅游旺季，建议尽早预订

--- 待核验清单 ---
□ 在OTA平台查询推荐区域的实际酒店和价格
□ 确认酒店取消政策
□ 检查是否含早餐
```

**Tools**（Phase 2 API集成后生效）：
- `search_hotels(city, checkin, checkout, guests, filters)` — 酒店搜索
- `get_area_recommendations(city)` — 区域推荐
- `compare_hotel_prices(hotel_id)` — 跨平台比价

---

### 3.4 行程Agent (Itinerary Agent)

**职责**：规划每日详细行程。

**输入**：
- 目的地
- 旅行天数（用户已确认的天数，或入口Agent提出的默认假设经用户确认后的值）
- 出发日期和返程日期
- 用户兴趣标签
- 住宿区域（由入口Agent预规划提供，与住宿Agent使用同一来源，不形成循环）
- 当地交通方式（来自交通Agent结果）
- 预算

> **MVP时间粒度说明**：MVP阶段交通Agent不输出具体航班时刻，因此行程Agent按"到达日（半天可用）/ 中间完整天 / 返程日（半天可用）"的粗粒度模板规划，首末日均假设半天可用于游览。Phase 2接入真实航班API后，根据实际到达/离开时刻精排首末日行程。

**MVP阶段输出**（行程规划是LLM擅长的方向性建议，可以较为详细，但不输出具体门票价格）：

```
===== 每日行程规划 =====
状态: 建议方案，可根据实际情况调整

--- Day 1: 抵达日（假设半天可用）---
主题: 到达与休整
- 抵达机场，前往市区（⚠️ 具体到达时间取决于航班，MVP阶段按半天可用估算）
- 酒店入住，稍作休息
- 酒店周边用餐，早些休息
💡 提示: 到达日以休息调整时差为主，不安排过多活动

--- Day 2: 经典伦敦 — 皇家与历史 ---
主题: 核心历史景点
- 上午: 白金汉宫（外观）& 卫兵换岗仪式（免费）
- 上午: 步行至威斯敏斯特教堂（⚠️ 门票需查官网）
- 午餐: 威斯敏斯特区域
- 下午: 大本钟 & 国会大厦（外观，免费）
- 下午: 伦敦眼（可选，⚠️ 门票需查官网）
- 傍晚: 泰晤士河南岸漫步
- 晚上: 晚餐

--- Day 3-N ... [按主题规划] ---

--- 待核验清单 ---
□ 确认各景点开放时间（部分景点周一闭馆）
□ 需要预约的景点提前在线预订
□ 查询景点门票价格（以官网为准）
```

**Tools**：
- `search_attractions(city, category)` — 景点搜索
- `get_opening_hours(attraction)` — 营业/开放时间
- `search_restaurants(city, cuisine, budget)` — 餐厅搜索
- `get_weather_forecast(city, date)` — 天气预报
- `calculate_route(from, to, mode)` — 路线计算

---

### 3.5 签证Agent (Visa Agent) — 按需启动

**职责**：查询签证要求和办理建议。

**输入**：
- 旅行者国籍
- 目的地国家
- 旅行日期

**MVP阶段输出**（签证信息属于高风险事实陈述，MVP阶段只输出方向性提醒，不输出具体费用和办理时长）：

```
===== 签证信息提醒 =====
状态: ⚠️ 仅为提醒，所有信息必须以官方渠道为准

--- 基本判断 ---
是否需要签证: 是（中国公民前往英国需要签证）
签证类型: 标准访客签证（Standard Visitor Visa）

--- 可能需要的材料（以使馆官网为准）---
- 有效护照
- 银行流水
- 在职证明或收入证明
- 住宿和交通预订确认
- 旅行保险

⚠️ 签证费用、办理时长和具体材料要求请查阅英国签证官方网站
⚠️ 建议尽早办理，预留充足处理时间

--- 待核验清单 ---
□ 访问英国签证官方网站确认最新要求
□ 确认护照有效期是否满足要求
□ 了解是否需要面签
□ 准备材料并预约递签
```

**Tools**（Phase 2 官方数据源接入后生效）：
- `check_visa_requirements(nationality, destination)` — 签证要求查询（需对接官方数据源）
- `get_embassy_info(country, city)` — 使领馆信息

---

## 四、通信机制

### 4.1 基于Codex邮箱的Agent间通信

**全部使用 `.txt` 文件**，确保与现有 `_room_snapshot()` (`router.py:470`) 和 `get_room_context()` (`templates.py:63-72`) 兼容。

```
.local_agent_ops/agent_mailbox/
├── 入口Agent_任务分发.txt            # 入口Agent下发的任务描述（纯文本）
├── 交通Agent_结果.txt                # 交通Agent的查询结果
├── 住宿Agent_结果.txt                # 住宿Agent的查询结果
├── 行程Agent_结果.txt                # 行程Agent的行程规划
├── 签证Agent_结果.txt                # 签证Agent的查询结果（如需要）
├── 汇总方案.txt                      # 最终汇总的旅行方案（Markdown格式，.txt后缀）
├── 执行人_给_审核人.txt               # 审核循环：执行人发件箱
├── 审核人_给_执行人.txt               # 审核循环：审核人发件箱
├── 共识状态.txt                      # 当前进度（现有）
├── 待决问题.txt                      # 待决问题（现有）
└── 轮次记录.txt                      # 交互记录（现有）
```

**设计决策**：
- 所有文件统一 `.txt` 后缀 → `_room_snapshot()` 的 `mailbox_dir.glob("*.txt")` 自动读取
- 子Agent结果文件内容可以是Markdown格式，但文件后缀保持 `.txt`
- 不引入 `.json` 或 `.md` 后缀的新文件，避免需要改动快照逻辑

### 4.2 上下文与快照改造方案

为让新增的子Agent结果文件进入Agent上下文和前端展示，需要做以下**小幅改动**：

**改动1：扩展 `get_room_context()` (`templates.py`)**

当前只暴露固定的 inbox/outbox/consensus/issues/rounds 5个文件。需要增加一个动态字段：

```python
def get_room_context(room_dir, role, other_role, workspace):
    ops = room_dir / ".local_agent_ops"
    mailbox = ops / "agent_mailbox"

    ctx = {
        # ... 现有字段保持不变 ...
        "workspace": workspace,
        "mailbox_dir": str(mailbox),
        "outbox_file": str(mailbox / f"{role}_给_{other_role}.txt"),
        "inbox_file": str(mailbox / f"{other_role}_给_{role}.txt"),
        "consensus_file": str(mailbox / "共识状态.txt"),
        "issues_file": str(mailbox / "待决问题.txt"),
        "rounds_file": str(mailbox / "轮次记录.txt"),
        "sender_role": other_role,
    }

    # [新增] 列出邮箱目录下所有子Agent结果文件，供模板引用
    result_files = [
        f.name for f in mailbox.glob("*Agent_结果.txt")
    ]
    ctx["sub_agent_result_files"] = ", ".join(result_files) if result_files else "（无）"
    ctx["summary_file"] = str(mailbox / "汇总方案.txt")

    return ctx
```

**改动2：前端邮箱侧栏已自动兼容**

当前前端 (`app.js`) 的邮箱侧栏直接渲染 `mailbox_files` 字典中的所有键值对。由于 `_room_snapshot()` 会读取所有 `*.txt` 文件，新增的子Agent结果文件**无需改动前端代码**即可自动展示。

### 4.3 消息格式

Agent间通信使用**纯文本**格式，每条消息包含统一的文本头：

```
===== 任务分发 =====
来源: 入口Agent
目标: 交通Agent
时间: 2026-10-01 08:00
任务类型: 交通方案查询

--- 任务内容 ---
出发地: 上海
目的地: 伦敦
出发日期: 2026-10-01
返回日期: 2026-10-08（用户已确认）
  ↳ 原始输入: 7-10天，经入口Agent建议8天7晚后用户确认
人数: 1
交通偏好: 飞机
预算: 中等
```

> **未确认天数时的替代格式**：如用户未确认精确天数，则用 `duration_range: 7-10天` 替代 `返回日期`，各子Agent按区间中值或最短天数规划，并在输出中标注"天数待用户确认"。

### 4.4 状态管理

任务状态通过 `sub_tasks` 数据库表管理（见8.1.3），不再用JSON文件。入口Agent可通过读取 `共识状态.txt` 了解当前进度，TravelOrchestrator 负责维护数据库状态。

---

## 五、Tools 设计

### 5.1 Tool 注册机制

每个Agent声明自己可用的Tools，入口Agent据此决定任务分配：

```python
AGENT_TOOLS = {
    "transport_agent": {
        "description": "交通方案查询与推荐",
        "tools": [
            {
                "name": "search_flights",
                "description": "搜索航班信息",
                "parameters": {
                    "origin": {"type": "string", "description": "出发城市IATA代码"},
                    "destination": {"type": "string", "description": "到达城市IATA代码"},
                    "date": {"type": "string", "format": "date"},
                    "passengers": {"type": "integer"}
                }
            },
            {
                "name": "search_trains",
                "description": "搜索火车/高铁信息",
                "parameters": {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                    "date": {"type": "string", "format": "date"}
                }
            }
        ]
    },
    "accommodation_agent": {
        "description": "住宿查询与推荐",
        "tools": [
            {
                "name": "search_hotels",
                "description": "搜索酒店",
                "parameters": {
                    "city": {"type": "string"},
                    "checkin": {"type": "string", "format": "date"},
                    "checkout": {"type": "string", "format": "date"},
                    "guests": {"type": "integer"},
                    "star_rating": {"type": "integer", "minimum": 1, "maximum": 5}
                }
            }
        ]
    },
    "itinerary_agent": {
        "description": "行程路线规划",
        "tools": [
            {
                "name": "search_attractions",
                "description": "搜索目的地景点",
                "parameters": {
                    "city": {"type": "string"},
                    "category": {"type": "string", "enum": ["历史文化", "自然风光", "博物馆", "美食", "购物", "娱乐"]}
                }
            },
            {
                "name": "get_weather_forecast",
                "description": "查询天气预报",
                "parameters": {
                    "city": {"type": "string"},
                    "date": {"type": "string", "format": "date"}
                }
            },
            {
                "name": "search_restaurants",
                "description": "搜索餐厅推荐",
                "parameters": {
                    "city": {"type": "string"},
                    "cuisine": {"type": "string"},
                    "budget": {"type": "string", "enum": ["economy", "mid_range", "luxury"]}
                }
            }
        ]
    }
}
```

### 5.2 Tool 实现方式

在当前阶段，Tools以两种方式实现：

**方式A：API集成（生产环境）**
```python
class FlightSearchTool:
    """对接真实航班API（如Amadeus, Skyscanner API）"""

    def execute(self, origin, destination, date, passengers):
        # 调用外部API
        response = amadeus_client.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=destination,
            departureDate=date,
            adults=passengers
        )
        return self._format_results(response.data)
```

**方式B：LLM知识推理（MVP阶段）— 限制为方向性建议**
```python
class FlightAdvisorTool:
    """MVP阶段：利用LLM知识给出方向性建议，禁止输出具体事实数据。"""

    def execute(self, origin, destination, date, passengers):
        prompt = f"""根据你的知识，给出从{origin}到{destination}的交通方式建议。

        要求：
        1. 推荐合适的交通方式（直飞/转机/火车等）
        2. 列出运营该航线的主要航空公司（仅列名称，不编造航班号）
        3. 说明大致飞行时间
        4. 不要输出具体票价、航班号、时刻表或订票链接
        5. 所有需要实时查询的信息标记为"待核验"
        6. 附上建议用户查询的官方渠道"""
        return llm.generate(prompt)
```

**MVP边界原则**：
- **可以输出**：方向性建议（推荐航线、推荐交通方式、推荐住宿区域、景点推荐、行程结构）+ 按预算档的区间粗估（见5.3节）
- **禁止输出**：具体航班号、票价、签证费用/时长、酒店价格、订票链接等依赖实时数据的事实信息
- 所有涉及实时事实的位置统一标记为"待核验"，并附"待核验清单"供用户逐项确认
- Phase 2接入真实API后，逐步开放具体数据输出

### 5.3 MVP阶段非实时预算粗估方案

> **设计动机**：需求概述要求输出"预算总览"，但MVP禁止输出实时价格。为在两者之间取得平衡，MVP阶段引入"按预算档的区间粗估"模块，基于LLM通用知识给出费用区间，明确标注非实时报价。

**预算粗估模块**：

```python
class BudgetEstimatorTool:
    """MVP阶段：基于预算档位和目的地给出费用区间粗估。

    不调用任何实时API，仅基于LLM通用知识。
    所有输出明确标注"仅作粗估，非实时报价"。
    """

    def execute(self, destination, duration_days, budget_level, travelers):
        prompt = f"""根据你的通用知识，给出{destination}{duration_days}天旅行的费用区间粗估。

        预算档位: {budget_level}（经济/中等/舒适）
        人数: {travelers}

        要求：
        1. 分项估算：国际交通、住宿、市内交通、餐饮、门票/活动
        2. 每项给出一个费用区间（如"¥3000-6000"），不要给精确数字
        3. 给出总预算区间
        4. 明确标注：所有金额仅为基于通用知识的粗估，非实时报价
        5. 附上建议用户查询实际价格的渠道"""
        return llm.generate(prompt)
```

**MVP预算粗估输出格式**：

```
===== 预算粗估 =====
状态: ⚠️ 仅作粗估，非实时报价，所有金额需自行核验

预算档位: 中等
目的地: 伦敦（8天7晚，1人）

--- 分项粗估 ---
国际往返机票:   ¥5,000 - ¥9,000（经济舱直飞，具体取决于预订时间和航司）
住宿（7晚）:    ¥4,000 - ¥8,000（3-4星酒店，Bloomsbury/South Kensington区域）
市内交通:       ¥500 - ¥1,000（Oyster Card / Contactless，Zone 1-2）
餐饮（8天）:    ¥2,500 - ¥5,000（中档餐厅 + 快餐搭配）
门票/活动:      ¥500 - ¥1,500（部分博物馆免费，付费景点按需）
通讯/保险/杂费: ¥500 - ¥1,000

--- 总预算区间 ---
合计粗估: ¥13,000 - ¥25,500

⚠️ 以上金额仅基于AI通用知识的区间估算，不构成报价
⚠️ 实际费用取决于预订时间、汇率、季节等因素
⚠️ 请通过携程/飞猪/Booking.com等平台查询实际价格

--- 待核验清单 ---
□ 查询实际机票价格
□ 查询实际酒店价格
□ 了解当前人民币/英镑汇率
```

**入口Agent调用时机**：预算粗估在Phase 3汇总阶段由入口Agent调用，汇入最终方案的"预算总览"章节。

---

## 六、完整工作流示例

### 6.1 用户场景：小明去伦敦

**Step 1: 用户输入**
> "我想在2026年10月1日从上海出发去伦敦旅游，大概7-10天"

**Step 2: 入口Agent解析**

提取到的要素：
```json
{
  "origin": "上海",
  "destination": "伦敦",
  "departure_date": "2026-10-01",
  "duration": "7-10天",
  "travelers": null,          // 缺失 → 需追问
  "budget": null,             // 缺失 → 提供默认值
  "transport_preference": null // 缺失 → 默认飞机
}
```

入口Agent追问：
> "好的！上海到伦敦的旅行听起来很棒。我还需要确认几个信息：
> 1. 几个人一起去？有小孩吗？
> 2. 大概的预算范围是？（经济/中等/舒适）
> 3. 有什么特别想去的地方或者特别感兴趣的活动吗？"

**Step 3: 用户补充**
> "就我一个人，预算中等就行，想看看博物馆和历史古迹"

**Step 3.5: 入口Agent确认天数假设**

用户给出的是区间"7-10天"，入口Agent提出默认假设并请用户确认：
> "明白了！关于行程天数，您说的是7-10天。我建议按 **8天7晚**（10月1日出发，10月8日返回）来规划，这样有充足时间游览伦敦核心景点。可以吗？如果您有更明确的返程日期或天数偏好，请告诉我。"

用户确认：
> "可以，就按8天吧"

此时 `duration_range: "7-10天"` 收敛为确认值 `duration: 8天`，`tentative_return_date: "2026-10-08"` 升级为 `confirmed_return_date: "2026-10-08"`。

> ⚠️ **关键设计点**：天数/返程日期必须经过用户确认才能进入后续规划。如果用户未确认，系统只输出区间型方案（如"7-10天灵活方案"），不固化具体天数。

**Step 4: 入口Agent制定计划**

```
需要的Agent：
✅ 签证Agent（中国→英国，需要签证）
✅ 交通Agent（查询上海→伦敦航班）
✅ 住宿Agent（伦敦住宿推荐）
✅ 行程Agent（博物馆+历史古迹路线规划）

执行计划（目标架构：Phase 1内可并行，MVP实际全程串行）：
Phase 1：签证Agent → 交通Agent → 住宿Agent（MVP串行执行）
Phase 2：行程Agent（依赖Phase 1结果）
Phase 3：汇总输出（含预算粗估）
```

> 注：以上展示的Phase分组反映任务依赖关系。目标架构中Phase 1内三个Agent可并行执行；MVP阶段全程串行，Phase 2迭代时升级为Phase内并行。

**Step 4.5: 入口Agent区域预规划（Phase 0）**

入口Agent根据"伦敦 + 博物馆兴趣"，确定推荐住宿区域为Bloomsbury/South Kensington，作为住宿Agent和行程Agent的共同输入。

**Step 5: 各Agent执行（Phase 1，MVP串行）**

> MVP阶段按 签证Agent → 交通Agent → 住宿Agent 顺序串行执行。目标架构中三者无相互依赖，可并行。

签证Agent → 输出签证类型提醒 + 待核验清单
交通Agent → 输出交通方式建议（航线、航司方向，不含具体航班号、票价和时刻）
住宿Agent → 输出住宿区域和类型建议（不含具体酒店价格）

**Step 6: 行程Agent规划（Phase 2）**

基于用户已确认的8天行程 + 住宿区域 + 交通方式 + 用户兴趣，按"到达日（半天）/ 中间完整天 / 返程日（半天）"粗粒度规划每日行程。不依赖具体航班时刻。

**Step 7: 入口Agent汇总（Phase 3）**

输出最终的 `汇总方案.txt`，包含：
1. 旅行概览（含天数确认来源说明）
2. 签证提醒（含待核验清单）
3. 交通方式建议（含待核验清单）
4. 住宿建议（含待核验清单）
5. 每日行程规划（已确认天数版）
6. 预算区间粗估
7. 综合待核验清单
8. 注意事项

---

## 七、最终方案输出格式（MVP版）

MVP阶段的方案输出分为两部分：**行程规划**（LLM可以给出的方向性建议）和**待核验清单**（需要人工查询实时数据的部分）。

```markdown
# 伦敦深度游 — 旅行方案（草案）

> ⚠️ 本方案由AI生成，其中涉及价格、航班、签证等实时信息的部分
> 标记为"待核验"，请在行动前通过官方渠道确认。

## 旅行概览
- 旅行者：小明（1人）
- 出发地：上海
- 目的地：伦敦，英国
- 日期：2026年10月1日 — 10月8日，8天7晚（用户原始输入"7-10天"，系统建议8天后经用户确认）
- 预算级别：中等
- 主题：博物馆 & 历史古迹

## 签证提醒
- 需办理：英国标准访客签证（Standard Visitor Visa）
- ⚠️ 签证费用和办理时长请查阅英国签证官方网站
- 建议尽早办理，预留充足处理时间
- 可能需要的材料：护照、银行流水、在职证明、保险等（以官方要求为准）

## 交通方案建议
- 推荐方式：直飞航班（上海浦东 → 伦敦希思罗）
- 运营航司：多家航司运营该航线（⚠️ 请查询实际航班和价格）
- 预计飞行时间：约11-13小时
- 市内交通：推荐使用Oyster Card或Contactless支付乘坐地铁/公交
- ⚠️ 具体航班、时刻和票价请通过携程/飞猪/航司官网查询

## 住宿建议
- 推荐区域：Bloomsbury / South Kensington（靠近博物馆区，交通便利）
- 推荐类型：3-4星商务酒店（符合中等预算）
- ⚠️ 具体酒店和价格请通过Booking.com/Hotels.com查询
- 10月为旺季，建议尽早预订

## 每日行程

### Day 1 — 到达日（假设半天可用）
- 抵达伦敦，前往市区（⚠️ 具体到达时间取决于航班，此处按半天可用规划）
- 酒店入住，稍作休息
- 酒店周边简单用餐
- 提示：到达日以休息调整时差为主，不安排过多活动

### Day 2 — 皇家与历史
- 上午：白金汉宫（外观）& 卫兵换岗仪式
- 上午：威斯敏斯特教堂
- 下午：大本钟 & 国会大厦（外观）
- 下午：伦敦眼（可选）
- 傍晚：泰晤士河南岸漫步

### Day 3 — 博物馆日
- 全天：大英博物馆（免费，建议至少半天）
- 下午：周边Bloomsbury区域探索
- 晚上：Covent Garden区域用餐

### Day 4-7 — [按主题继续规划]
- Day 4: 塔桥 & 伦敦塔 & 金融城
- Day 5: 南肯辛顿博物馆群（V&A、自然历史、科学博物馆）
- Day 6: 格林威治 & 泰晤士河游船
- Day 7: 自由活动 / 购物 / 近郊一日游

### Day 8 — 返程日（假设半天可用）
- 酒店退房，最后的购物或补充游览（视航班时间而定）
- 前往机场，返程（⚠️ 具体出发时间取决于航班，此处按半天可用规划）

## 预算粗估

> ⚠️ 以下金额仅基于AI通用知识的区间估算，非实时报价，请通过实际平台查询确认。

| 费用项 | 粗估区间（人民币） | 说明 |
|--------|-------------------|------|
| 国际往返机票 | ¥5,000 - ¥9,000 | 经济舱直飞，取决于预订时间 |
| 住宿（7晚，基于用户确认天数） | ¥4,000 - ¥8,000 | 3-4星酒店，Bloomsbury区域 |
| 市内交通 | ¥500 - ¥1,000 | Oyster Card，Zone 1-2 |
| 餐饮（8天，基于用户确认天数） | ¥2,500 - ¥5,000 | 中档餐厅+快餐搭配 |
| 门票/活动 | ¥500 - ¥1,500 | 部分博物馆免费 |
| 通讯/保险/杂费 | ¥500 - ¥1,000 | — |
| **合计粗估** | **¥13,000 - ¥25,500** | 中等预算档 |

⚠️ 实际费用取决于预订时间、汇率（英镑/人民币）、季节等因素，请以实际查询为准。

## 待核验清单

以下事项需要您在行动前通过官方渠道确认：

### 必须核验
- □ 签证：访问英国签证官方网站确认要求、费用和办理时长
- □ 航班：查询实际航班、时刻和票价
- □ 住宿：在OTA平台查询推荐区域的酒店和价格
- □ 护照：确认有效期满足要求

### 建议核验
- □ 景点：确认各景点开放时间和门票价格（以官网为准）
- □ 天气：出行前查看10月伦敦天气预报
- □ 通讯：了解国际漫游/本地SIM卡方案
- □ 保险：购买合适的旅行保险
- □ 转换器：英国使用英标三脚插头

## 注意事项
1. 10月伦敦气温约8-15°C，多雨，请备好防雨外套
2. 英国与中国时差7-8小时
3. 许多博物馆免费但建议预约
4. 英镑为当地货币，大部分地方可刷卡
```

---

## 八、技术实现计划

### 8.1 与Codex平台集成

基于现有Codex平台架构，扩展以下模块：

#### 8.1.1 新增 Agent 角色模板

在 `templates/` 目录下新增旅游Agent的角色模板，采用**扁平命名**（当前 `templates.py:25` 禁止模板名包含 `/` 或 `\`，不支持子目录）：

```
templates/
├── onboarding.txt                          # 现有
├── trigger_execute.txt                     # 现有
├── trigger_review.txt                      # 现有
├── trigger_respond.txt                     # 现有
├── trigger_recover.txt                     # 现有
├── travel_entry_agent_role.txt             # [新增] 入口Agent角色定义
├── travel_transport_agent_role.txt         # [新增] 交通Agent角色定义
├── travel_accommodation_agent_role.txt     # [新增] 住宿Agent角色定义
├── travel_itinerary_agent_role.txt         # [新增] 行程Agent角色定义
├── travel_visa_agent_role.txt              # [新增] 签证Agent角色定义
├── travel_trigger_subtask.txt              # [新增] 子任务分发模板
└── travel_trigger_aggregate.txt            # [新增] 结果汇总模板
```

**命名规范**：所有旅游相关模板统一以 `travel_` 前缀区分，避免与现有模板冲突。

#### 8.1.2 新增 TravelOrchestrator（多Agent任务编排器）

**不修改现有 Router**，而是新增独立模块 `backend/app/travel_orchestrator.py`。

**设计理由**：
- 现有 Router 的 `Turn = Literal["executor", "reviewer"]` 和 `_auto_loop()` 是围绕双角色设计的，强行扩展会破坏其简洁性
- 旅游场景需要DAG（有向无环图）任务依赖调度，与双角色轮转在本质上不同
- 新增独立模块可以复用 `SessionManager` 和 `Store`，但不干扰现有代码路径

**需要新增的能力清单**：

| 能力 | 现有模块是否支持 | 改造方式 |
|------|------------------|----------|
| 多角色session创建 | `SessionManager.create_session(role, provider, workspace)` — role字段可传任意字符串，**已支持** | 无需改动 |
| 多角色消息记录 | `Store.add_message(sender)` — sender字段可传任意字符串，**已支持** | 无需改动 |
| session与room关联 | `Store.add_session(session_id, room_id, role, ...)` — **已支持** | 无需改动 |
| DAG任务依赖调度 | **不支持**，当前只有线性轮转 | **TravelOrchestrator 核心功能** |
| 子任务状态跟踪 | **不支持** | **新增 sub_tasks 表** |
| 并行Agent执行 | **不支持**，当前一次只运行一个Agent | **TravelOrchestrator 线程池** |
| 结果汇总触发 | **不支持** | **TravelOrchestrator 完成回调** |
| 超时与失败重试 | `_auto_loop` 有连续失败计数，但不支持单Agent重试 | **TravelOrchestrator 重试逻辑** |

**TravelOrchestrator 核心设计**：

```python
# backend/app/travel_orchestrator.py
"""旅游Agent App的多Agent任务编排器。

独立于Router，复用SessionManager和Store。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from . import templates
from .session_mgr import SessionManager
from .store import Store

Phase = Literal["collecting", "dispatching", "executing", "aggregating", "completed"]


class TravelOrchestrator:
    """多Agent DAG任务编排器。"""

    MAX_AGENT_TIMEOUT = 300   # 单个Agent最大执行时间（秒）
    MAX_RETRIES = 2           # 单个子任务最大重试次数

    def __init__(self, store: Store, session_mgr: SessionManager, runtime_root: Path):
        self.store = store
        self.session_mgr = session_mgr
        self.runtime_root = runtime_root
        self._executor_pool = ThreadPoolExecutor(max_workers=4)

    def start_travel_session(self, room_id: str, user_request: str) -> None:
        """创建旅游规划会话，启动入口Agent进行要素提取。"""
        # 1. 创建入口Agent session（复用现有create_session接口）
        entry_session = self.session_mgr.create_session(
            role="entry_agent", provider="claude",
            workspace=self.store.get_room(room_id)["workspace"],
        )
        self.store.add_session(
            entry_session.session_id, room_id, "entry_agent", "claude",
            entry_session.cli_session_id,
        )

        # 2. 发送角色模板 + 用户请求（扁平模板命名）
        prompt = templates.render("travel_entry_agent_role", request=user_request)
        self.session_mgr.send_message(entry_session.session_id, prompt)

    def dispatch_sub_tasks(self, room_id: str, task_plan: list[dict]) -> None:
        """根据入口Agent的计划，按依赖顺序分发子任务。

        task_plan 示例:
        [
            {"agent_type": "transport_agent", "phase": 1, "input": {...}},
            {"agent_type": "accommodation_agent", "phase": 1, "input": {...}},
            {"agent_type": "itinerary_agent", "phase": 2, "input": {...},
             "depends_on": ["transport_agent", "accommodation_agent"]},
        ]
        """
        # 按phase分组
        phases = {}
        for task in task_plan:
            p = task["phase"]
            phases.setdefault(p, []).append(task)

        # 逐phase执行（phase内并行，phase间串行）
        for phase_num in sorted(phases.keys()):
            phase_tasks = phases[phase_num]
            futures = []
            for task in phase_tasks:
                future = self._executor_pool.submit(
                    self._run_sub_agent, room_id, task
                )
                futures.append((task["agent_type"], future))

            # 等待当前phase所有任务完成
            for agent_type, future in futures:
                try:
                    future.result(timeout=self.MAX_AGENT_TIMEOUT)
                    self.store.update_sub_task_status(
                        room_id, agent_type, "completed"
                    )
                except Exception as exc:
                    self.store.update_sub_task_status(
                        room_id, agent_type, "failed", error=str(exc)
                    )

    def _run_sub_agent(self, room_id: str, task: dict) -> str:
        """执行单个子Agent任务。"""
        agent_type = task["agent_type"]
        workspace = self.store.get_room(room_id)["workspace"]

        # 创建子Agent session
        session = self.session_mgr.create_session(
            role=agent_type, provider="claude", workspace=workspace,
        )
        self.store.add_session(
            session.session_id, room_id, agent_type, "claude",
            session.cli_session_id,
        )

        # 发送角色模板（扁平命名: travel_{agent_type}_role）
        template_name = f"travel_{agent_type}_role"
        prompt = templates.render(template_name, task_input=str(task["input"]))
        result = self.session_mgr.send_message(session.session_id, prompt)

        # 子Agent将结果写入邮箱txt文件，此处返回输出文本
        return result.output_text or ""

    def trigger_aggregation(self, room_id: str) -> None:
        """所有子任务完成后，触发入口Agent汇总结果。"""
        entry_session = self._get_entry_session(room_id)
        prompt = templates.render("travel_trigger_aggregate", room_id=room_id)
        self.session_mgr.send_message(entry_session.session_id, prompt)

    def _get_entry_session(self, room_id: str):
        """获取入口Agent的session。"""
        sessions = self.store.get_sessions_for_room(room_id)
        return next(s for s in sessions if s["role"] == "entry_agent")
```

**与现有Router的关系**：
- Router 继续负责「执行人 ↔ 审核人」的协作流程（方案写好后的审核轮次）
- TravelOrchestrator 负责「入口Agent → 子Agent并行执行 → 汇总」的编排流程
- 两者共享 `SessionManager` 和 `Store`，但各自管理自己的调度逻辑
- 工作流：TravelOrchestrator 生成旅行方案 → 方案进入 Router 的执行人/审核人审核循环

#### 8.1.3 扩展 Store

新增 `sub_tasks` 表：

```sql
CREATE TABLE sub_tasks (
    task_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,        -- transport_agent, accommodation_agent, etc.
    status TEXT DEFAULT 'pending',   -- pending, in_progress, completed, failed
    input_payload TEXT,              -- JSON: 任务输入
    output_payload TEXT,             -- JSON: 任务结果
    depends_on TEXT,                 -- JSON array: 依赖的其他task_id
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);
```

#### 8.1.4 扩展 Scaffolder

为旅游房间创建额外的文件结构（所有文件使用 `.txt` 后缀，兼容现有快照逻辑）：

```python
def scaffold_travel_room(room_id, workspace):
    """在标准房间结构基础上，增加旅游Agent通信文件。"""
    # 先创建标准结构
    scaffold_room(room_id, workspace, "执行人", "审核人")

    # 增加子Agent结果文件（全部 .txt 后缀）
    mailbox = f"{workspace}/.local_agent_ops/agent_mailbox"
    for agent in ["交通Agent", "住宿Agent", "行程Agent", "签证Agent"]:
        write_file(f"{mailbox}/{agent}_结果.txt", f"# {agent}结果\n\n（等待执行）")

    write_file(f"{mailbox}/入口Agent_任务分发.txt", "# 任务分发\n\n（等待入口Agent规划）")
    write_file(f"{mailbox}/汇总方案.txt", "# 旅行方案\n\n（等待生成）")
```

**兼容性说明**：
- 所有新增文件均为 `.txt` 后缀 → `_room_snapshot()` 的 `glob("*.txt")` 自动读取
- 前端邮箱侧栏自动展示所有 `mailbox_files` 键值对 → 无需改动前端
- 子Agent结果文件内容可以是Markdown格式，但后缀保持 `.txt`

### 8.2 实现阶段划分

#### Phase 1: MVP（核心流程验证）

**目标**：跑通完整流程，输出方向性建议 + 预算区间粗估 + 待核验清单

**MVP边界**：
- **可以做**：需求收集、结构化行程规划、景点/主题推荐、按预算档的区间粗估（非实时）、待核验清单生成
- **不做**：具体航班号/票价/签证费用/酒店价格/订票链接等依赖实时API的数据输出
- **调度方式**：全程串行（目标架构为Phase内并行，Phase 2迭代时升级）

**任务清单**：
- [ ] 入口Agent角色模板 (`travel_entry_agent_role.txt`) + 要素提取prompt + 区域预规划prompt
- [ ] 交通/住宿/行程Agent角色模板（`travel_*_agent_role.txt`），含MVP输出边界约束
- [ ] TravelOrchestrator 模块 (`backend/app/travel_orchestrator.py`)：MVP阶段先实现串行调度
- [ ] 邮箱文件结构：子Agent结果文件（全部 `.txt` 后缀）
- [ ] 汇总模板 (`travel_trigger_aggregate.txt`)：生成最终方案
- [ ] `templates.py` 扩展：`get_room_context()` 增加 `sub_agent_result_files` 和 `summary_file` 字段
- [ ] `store.py` 扩展：新增 `sub_tasks` 表
- [ ] 前端：子任务进度可视化（可复用现有邮箱侧栏，无需大改）

**MVP产出**：用户输入旅行需求 → 系统输出行程规划方案 + 待核验清单

#### Phase 2: 增强（API集成）

- [ ] 对接Amadeus/Skyscanner航班API
- [ ] 对接Booking.com/Hotels.com住宿API
- [ ] 对接Google Places景点API
- [ ] 对接天气API
- [ ] 真实价格数据替代LLM推理
- [ ] 支持订票链接跳转

#### Phase 3: 高级功能

- [ ] 方案对比（生成多套方案供用户选择）
- [ ] 实时价格监控
- [ ] 行程共享与导出（PDF/日历）
- [ ] 多人旅行协作
- [ ] 预算追踪
- [ ] 旅行日记 / 复盘

---

## 九、风险与待决问题

### 9.1 已识别风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MVP输出方向性建议价值有限 | 用户觉得"空洞" | 行程规划部分尽量详细（景点/主题/路线是LLM擅长的）；新增预算区间粗估提供费用参考感；强化"待核验清单"作为行动指南 |
| 多Agent并发通信复杂度 | 结果不一致或丢失 | 入口Agent作为中心协调者，TravelOrchestrator管理DAG状态 |
| 子Agent超时或失败 | 方案不完整 | TravelOrchestrator设置超时（300秒）+ 重试（2次）+ 降级方案 |
| 签证/交通等实时信息 | 误导用户 | MVP严格禁止输出具体价格/航班号/签证费用；Phase 2接入API后逐步开放 |
| TravelOrchestrator新增模块复杂度 | 开发和测试成本 | MVP先实现串行调度，Phase 2再优化为并行 |

### 9.2 待决问题

#### 已闭合

1. ~~**子Agent是否需要独立的CLI session？**~~ → **是**。每个子Agent一个session，通过session隔离上下文，保持与Codex架构一致。（已体现在8.1.2 TravelOrchestrator设计中）
2. ~~**最终方案输出格式？**~~ → **Markdown格式（.txt后缀）**，兼容现有邮箱系统的`glob("*.txt")`。（已体现在第四章和第七章）
3. ~~**是否支持方案修改？**~~ → **MVP不支持**。用户提出修改需求时提示"请在方案基础上手动调整，部分重新规划能力将在后续版本支持"。（Phase 2考虑）
4. ~~**MVP是否串行执行子Agent？**~~ → **MVP全程串行**。目标架构为Phase内并行、Phase间串行的DAG调度；MVP先以串行落地降低首版复杂度，Phase 2升级为Phase内并行。（已统一到第三章执行顺序和第八章实现计划）

#### 已闭合（v1.3新增）

5. ~~**TravelOrchestrator与Router的HTTP入口如何设计？**~~ → **选项A：独立端点**。在 `server.py` 新增 `/api/travel/start`、`/api/travel/status`、`/api/travel/approve` 等独立端点，与现有 `/api/rooms/*/round` 分离。
   - **选择理由**：
     - 关注点分离：旅游编排（多Agent DAG）与通用协作（双角色轮转）是不同的调度模型，共享端点会导致路由逻辑复杂化
     - 独立演进：旅游端点可以独立扩展（如增加子任务进度查询 `/api/travel/{id}/subtasks`），不影响现有通用房间的API稳定性
     - 维护成本可控：新增3-4个端点，每个端点逻辑简单（委托给TravelOrchestrator），代码量有限
   - **端点设计**：
     - `POST /api/travel/start` — 创建旅游规划会话，启动入口Agent
     - `GET /api/travel/{id}/status` — 查询当前编排进度（含各子Agent状态）
     - `POST /api/travel/{id}/confirm` — 用户确认要素（如天数确认）
     - `POST /api/travel/{id}/approve` — 方案审核通过
     - `GET /api/travel/{id}/plan` — 获取最终汇总方案

---

## 十、执行人-审核人协作流程

旅行方案生成后，进入"执行人-审核人"协作审核循环，直到双方达成共识。

> **角色映射说明**：本方案涉及两个阶段的角色：
> - **Phase A（方案生成）**：入口Agent 作为编排角色协调各子Agent（交通/住宿/行程/签证）
> - **Phase B（审核循环）**：方案提交方为"执行人"，审核方为"审核人"
> - 入口Agent 在完成 Phase A 汇总后，以"执行人"身份进入 Phase B 审核循环
> - 邮箱文件统一使用"执行人/审核人"命名：`执行人_给_审核人.txt`、`审核人_给_执行人.txt`

### 10.1 角色定义

| 角色 | 职责 | 产出 |
|------|------|------|
| 执行人 | 驱动入口Agent完成方案生成，并根据审核人反馈修改方案 | 汇总方案.txt（旅行方案）、执行人_给_审核人.txt（工作汇报） |
| 审核人 | 审核方案质量、一致性、合理性，提出修改意见 | 审核人_给_执行人.txt（审核意见） |

### 10.2 协作流程

```
┌─────────────────────────────────────────────┐
│ Phase A: 方案生成（TravelOrchestrator 驱动） │
│  入口Agent → 子Agent执行 → 汇总方案.txt      │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│ Phase B: 审核循环（Router 驱动）             │
│                                             │
│  ┌──────────┐    审核意见    ┌──────────┐   │
│  │  执行人   │◄─────────────│  审核人   │   │
│  │ 修改方案  │─────────────►│ 审核方案  │   │
│  └──────────┘    修改后方案  └──────────┘   │
│        │                          │         │
│        └──── 达成共识？───────────┘         │
│              │是                             │
│              ▼                               │
│        共识状态.txt ← 已达成共识               │
└─────────────────────────────────────────────┘
                  │
                  ▼
          方案定稿，流程结束
```

### 10.3 `共识状态.txt` 状态字面量

`共识状态.txt` 的"共识状态"字段使用以下标准值（脚本和模板按此字面量判断）：

| 状态值 | 含义 |
|--------|------|
| `未开始` | 方案尚未生成 |
| `审核中` | 方案已提交，审核循环进行中 |
| `需修改` | 审核人提出修改意见，等待执行人修改 |
| `已达成共识` | 双方确认方案定稿，流程结束 |

### 10.4 轮次规则

1. **每轮次**执行人将方案和工作说明写入发件箱，审核人审阅后将意见写入其发件箱
2. 执行人必须**逐条回应**审核人的每条意见（接受/拒绝+理由）
3. 如有分歧，记录到 `待决问题.txt`，双方讨论后闭合
4. 每轮次摘要记录到 `轮次记录.txt`
5. 共识达成后更新 `共识状态.txt` 为 `已达成共识`

### 10.5 审核检查清单

审核人应从以下维度审核旅行方案：

| 维度 | 检查要点 |
|------|----------|
| 完整性 | 是否涵盖签证、交通、住宿、行程、预算全部板块 |
| 一致性 | 天数、日期、区域等信息在各章节是否一致 |
| 合理性 | 行程安排是否考虑了时差、距离、开放时间等实际因素 |
| MVP边界 | 是否遵守了MVP不输出实时价格的约束，待核验标记是否齐全 |
| 可执行性 | 待核验清单是否清晰、可操作 |
| 用户意图 | 是否忠实于用户原始需求（目的地、兴趣、预算等） |

### 10.6 异常场景处理

| 异常场景 | 处理策略 |
|----------|----------|
| 审核人连续3轮未通过 | 双方整理分歧列表，升级为待决问题逐项讨论 |
| 执行人不同意审核意见 | 在发件箱中给出具体理由和替代方案，由审核人判断是否接受 |
| 子Agent结果缺失或质量差 | 执行人在汇总时标注缺失部分并说明原因，审核人可要求补充或接受降级 |
| 新需求变更（用户中途改目的地等） | 重新进入Phase A方案生成，重置审核循环 |

---

## 十一、总结

本方案设计了一个基于Codex平台的旅游计划Agent App，核心思路是：

1. **入口Agent为中心**：负责理解用户意图、区域预规划、分解任务、协调子Agent、汇总结果
2. **专业子Agent分工**：交通、住宿、行程、签证各司其职，无循环依赖
3. **复用Codex基础设施**：邮箱通信（全部.txt）、Session管理、状态持久化，小幅扩展 `get_room_context()` 和 `sub_tasks` 表
4. **新增TravelOrchestrator**：独立的多Agent DAG任务编排器，不修改现有Router
5. **MVP边界清晰**：方向性建议 + 按预算档的区间粗估 + 待核验清单；禁止输出依赖实时API的事实信息；Phase 2接入API后逐步开放
6. **渐进式实现**：MVP全程串行调度验证流程 → Phase 2升级Phase内并行 + API集成 → Phase 3高级功能

7. **执行人-审核人协作流程**：方案生成后进入审核循环，通过邮箱机制逐轮迭代直至双方达成共识

该方案在保持Codex平台"系统搭脚手架、Agent负责思考和写作"哲学的基础上，通过新增独立编排模块扩展了多Agent协作能力，适合作为Codex平台的首个垂直领域应用。
