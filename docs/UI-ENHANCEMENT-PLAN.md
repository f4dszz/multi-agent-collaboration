# UI Enhancement Plan — 像素风办公室主题

## 灵感来源

[Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI) — 像素风 AI 办公室看板，将 agent 工作状态映射到像素角色在房间中的位置和动画。

## Star-Office 技术拆解

通过阅读源码，确认其核心技术栈：

| 组件 | 技术 | 细节 |
|------|------|------|
| 游戏引擎 | **Phaser.js 3** | `Phaser.AUTO`（WebGL优先，Canvas降级），`pixelArt: true` |
| 渲染画布 | 1280×720 Canvas | 嵌入 `#game-container` div |
| 布局管理 | `layout.js` | 所有坐标、depth、缩放集中配置，避免 magic number |
| 场景逻辑 | `game.js` | preload→create→update 三段式，状态驱动角色移动 |
| 精灵动画 | Spritesheet 网格切帧 | 如 star_working: 230×144px/帧，192帧，12fps |
| 状态映射 | 6种状态 → 3个区域 | idle→休息区, writing/executing→工位, error→bug区 |
| 气泡系统 | Phaser Graphics + Text | 打字机效果，随机文案轮播，8秒间隔 |
| 交互 | 点击家具换帧 | 植物/海报/猫随机切换精灵帧 |
| 后端轮询 | fetch('/status') | 每2秒拉取状态，驱动角色切换 |
| 素材格式 | WebP优先 + PNG降级 | 透明素材强制PNG，运行时检测浏览器WebP支持 |

## 目标

在**不改变任何后端逻辑和功能**的前提下，将当前深色终端风前端改造为像素风办公室主题：
- 两个 agent 拟人化为像素角色（执行人 + 监督人）
- 办公室场景作为背景，agent 状态映射到不同区域/动画
- 保留全部功能：Room 管理、聊天流、邮箱查看、操作按钮
- 像素场景作为顶部装饰层，业务面板仍是DOM元素

## 技术选型

| 方向 | 选择 | 理由 |
|------|------|------|
| 游戏引擎 | **Phaser.js 3**（CDN引入） | 与 Star-Office 一致，成熟的2D精灵/动画/物理引擎 |
| 素材生成 | **AI 生图**（Midjourney/DALL-E/本地SD）| 自定义双角色 + 办公室背景，避免版权问题 |
| 像素字体 | Press Start 2P（Google Fonts）+ 方正像素字体 | 标题/按钮用像素字体，正文保留可读字体 |
| 布局 | 借鉴 layout.js 模式 | 坐标/depth 集中管理，与 Star-Office 结构一致 |
| 集成方式 | Phaser Canvas 嵌入顶部 + 下方 DOM 面板 | 场景是纯装饰，不承载业务逻辑 |

## 页面布局方案

```
┌──────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────────┐  │
│  │         Phaser Canvas（像素办公室场景）               │  │
│  │                                                    │  │
│  │   [执行人角色]        [监督人角色]                    │  │
│  │   💻 工位区           📋 审核区                      │  │
│  │         [咖啡机] [植物] [猫]                         │  │
│  │                                                    │  │
│  │   状态气泡: "正在编码..."   "等待审核..."              │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────┬─────────────────────────┬──────────────┐  │
│  │ Room列表  │   聊天消息流（像素风气泡） │  邮箱文件     │  │
│  │          │                         │  查看器       │  │
│  │ [Room 1] │  [像素头像] EXECUTOR:    │              │  │
│  │ [Room 2] │  我已完成修改...         │  执行人邮箱   │  │
│  │          │  [像素头像] REVIEWER:    │  监督人邮箱   │  │
│  │          │  审核通过...            │  共识状态     │  │
│  │          │                         │              │  │
│  │          │ [操作栏] [消息输入]      │              │  │
│  └──────────┴─────────────────────────┴──────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Agent 拟人化设计

### 角色设定

| Agent | 像素角色 | 工位区域 | 精灵状态 |
|-------|---------|---------|---------|
| **执行人** | 程序员（戴耳机/帽衫） | 左侧电脑桌 | idle: 坐着喝咖啡, working: 打字+屏幕闪, error: 头上冒烟 |
| **监督人** | 审查官（眼镜/正装） | 右侧审核桌 | idle: 看报纸, working: 翻文件, approved: 竖拇指 |

### 状态 → 场景映射（借鉴 Star-Office STATES 模式）

```javascript
const AGENT_STATES = {
  onboarding:        { executor: 'walking_to_desk', reviewer: 'walking_to_desk' },
  awaiting_task:     { executor: 'idle_coffee',     reviewer: 'idle_newspaper' },
  working_executor:  { executor: 'typing',          reviewer: 'idle' },
  working_reviewer:  { executor: 'idle',            reviewer: 'reviewing' },
  awaiting_approval: { executor: 'standing',        reviewer: 'standing' },
  completed:         { executor: 'celebrate',       reviewer: 'celebrate' },
};
```

## 素材需求清单（AI 生图）

### 必需素材（优先级 P0）

| 素材 | 规格 | Prompt 方向 |
|------|------|------------|
| 办公室背景 | 1280×400px | "pixel art cozy office room, two desks, warm lighting, side view, 32-bit style" |
| 执行人-idle | 128×128 spritesheet, 6帧 | "pixel art character sitting at desk, drinking coffee, programmer hoodie, 6 frame animation strip" |
| 执行人-typing | 230×144 spritesheet, 12帧 | "pixel art programmer typing at computer, screen glowing, 12 frame animation" |
| 监督人-idle | 128×128 spritesheet, 6帧 | "pixel art character reading newspaper, glasses, formal shirt, 6 frame animation" |
| 监督人-reviewing | 230×144 spritesheet, 12帧 | "pixel art inspector reviewing documents, writing notes, 12 frame animation" |
| 办公桌×2 | 各 200×150px（透明PNG）| "pixel art office desk with computer, side view, transparent background" |

### 装饰素材（P1）

| 素材 | 规格 | 说明 |
|------|------|------|
| 咖啡机 | 230×230 spritesheet | 冒烟动画 |
| 植物盆栽 | 160×160 多帧 | 随机品种 |
| 猫 | 160×160 多帧 | 桌面装饰，可点击 |
| 公告板 | 200×300px | 邮箱文件区域的视觉映射 |

### 可用开源素材备选

- [LimeZu - Modern Interiors](https://limezu.itch.io/moderninteriors)（免费，适合办公室家具）
- [LimeZu - Animated Characters](https://limezu.itch.io/animated-mini-characters-2-platform-free)（免费，角色动画）
- 注意：部分素材仅限非商用

## 实施步骤

### Phase 1: 基础搭建
1. **引入 Phaser.js** — CDN 方式加载到 index.html
2. **创建 `office-layout.js`** — 借鉴 Star-Office 的 layout.js，定义双工位坐标
3. **创建 `office-scene.js`** — preload/create/update 三段式，初始化空场景
4. **占位素材** — 用纯色矩形占位，验证布局和深度层级
5. **集成到页面** — Canvas 放在业务面板上方

### Phase 2: 素材与动画
6. **生成/制作素材** — AI 生图 → 裁切为 spritesheet 网格
7. **角色精灵** — 加载 spritesheet，创建逐帧动画（`steps()` 式）
8. **家具与装饰** — 办公桌、咖啡机、植物、猫
9. **背景渲染** — 加载像素办公室背景图

### Phase 3: 状态联动
10. **桥接 app.js ↔ office-scene.js** — 暴露 `updateOfficeState(roomState, busyAgent)` 方法
11. **角色移动** — 状态切换时角色走向对应区域（Phaser physics 或 tween）
12. **气泡系统** — Phaser Graphics 绘制像素气泡 + 打字机效果
13. **Agent 关联** — executor/reviewer 状态分别驱动各自角色

### Phase 4: UI 像素化
14. **像素字体** — 引入 Press Start 2P，应用到标题和按钮
15. **配色方案** — 暖色像素办公室调色板替代深色终端风
16. **按钮样式** — 像素风凸起按钮（box-shadow 模拟 3D 边框）
17. **消息气泡** — 像素风边框 + 角色头像

### Phase 5: 打磨
18. **交互细节** — 点击家具换帧、猫的气泡
19. **加载进度条** — 仿 Star-Office 的像素进度条
20. **响应式** — 移动端场景缩放
21. **性能** — WebP 优先 + PNG 降级，懒加载

## 文件变更范围

```
frontend/site/
├── index.html              # 添加 Phaser CDN + game-container div
├── styles.css              # 像素风配色 + 按钮样式 + 字体
├── app.js                  # 添加 updateOfficeState() 桥接调用（~20行）
├── office-layout.js        # 新增：坐标/depth/素材配置（借鉴 layout.js）
├── office-scene.js         # 新增：Phaser 场景逻辑（借鉴 game.js）
└── assets/                 # 新增目录
    ├── sprites/            # 角色 spritesheet PNG/WebP
    ├── backgrounds/        # 办公室背景图
    ├── furniture/          # 家具素材
    └── fonts/              # 像素字体（如不用 CDN）
```

**不涉及的文件**：backend/\*、templates/\*、tests/\*

## 风险与注意事项

1. **Phaser.js 体积** — CDN 引入约 500KB gzip，首次加载增加约 1 秒
2. **素材质量** — AI 生成的 spritesheet 帧一致性是挑战，可能需手动微调
3. **中文像素字体** — 正文保留系统字体，仅标题/按钮用像素字体
4. **降级方案** — Phaser 加载失败时，业务面板仍可正常使用（独立 DOM）
5. **素材版权** — AI 生成素材归自有，开源素材需遵守许可（LimeZu: 非商用）
