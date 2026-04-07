# AI 生成像素素材实操指南

## 工具选择

| 工具 | 优势 | 适合生成 |
|------|------|---------|
| **Midjourney** | 风格一致性最好 | 背景场景、静态家具 |
| **ChatGPT (DALL-E)** | 最方便、支持对话迭代 | 单帧角色、UI元素 |
| **Stable Diffusion + LoRA** | 本地免费、可控性强 | Spritesheet 批量帧 |

---

## 方法一：Midjourney（推荐用于背景和家具）

### 基本 Prompt 结构
```
[主体描述], pixel art, 16-bit style, [视角], [配色], --ar [比例] --s [风格化] --niji 6
```

### 办公室背景
```
cozy pixel art office room interior, two computer desks side by side, 
warm wood floor, bookshelves on wall, potted plants, coffee machine in corner, 
side view, 16-bit retro game style, warm lighting, 
--ar 16:5 --s 250 --niji 6
```

### 办公桌（透明背景单品）
```
pixel art office desk with computer monitor and keyboard, 
isometric side view, 16-bit style, simple clean design, 
white background, game asset sprite, 
--s 100 --niji 6
```

### 关键参数
- `--ar 16:5` → 宽横幅背景
- `--s 100~250` → 风格化程度（低=写实，高=艺术化）
- `--niji 6` → 动漫/游戏风格模型（像素画效果更好）
- 加 `--no realistic, 3d, photograph` 排除写实风

---

## 方法二：ChatGPT + DALL-E（推荐用于角色）

### 直接对话式生成

跟 ChatGPT 说：
```
帮我生成一个像素风格的角色精灵图（spritesheet）：
- 角色：一个戴耳机的程序员，穿帽衫
- 32-bit 像素风格
- 需要4个状态帧排成一行：
  1. 坐着喝咖啡（idle）
  2. 打字中（typing）
  3. 头上冒问号（thinking）
  4. 举手庆祝（celebrate）
- 每帧 128x128 像素
- 简单纯色背景（便于抠图）
- 统一的角色比例和风格
```

### 迭代优化
```
第一帧很好，但第二帧打字的姿势不够明显，能否：
1. 让手的位置更靠近键盘
2. 屏幕加一些绿色代码光
3. 保持和第一帧完全一样的角色比例和配色
```

### 技巧
- **分帧生成**比一次生成整个 spritesheet 质量更高
- 生成后用 Photoshop/GIMP 拼接成网格
- 让 ChatGPT "保持和上一张图一样的风格" 来维持一致性

---

## 方法三：Stable Diffusion + Pixel Art LoRA（推荐大批量）

### 环境
- ComfyUI 或 Automatic1111
- 基础模型：SD 1.5 或 SDXL
- LoRA：搜索 CivitAI 上的 "pixel art" LoRA

### 推荐 LoRA
- **Pixel Art XL** — SDXL 专用，效果好
- **Pixel Art Style** — SD1.5，经典选择
- 在 CivitAI (https://civitai.com) 搜索 "pixel art spritesheet"

### Prompt 模板
```
正向: pixel art, game sprite, [角色描述], 16-bit, retro game style, 
      clean pixels, <lora:pixel_art:0.8>
负向: blurry, realistic, 3d render, photograph, anti-aliasing, smooth
```

### 批量帧生成
1. 用 img2img 模式，固定种子
2. 只改变姿势描述词
3. 保持 denoise 在 0.4~0.6（维持一致性）

---

## 后期处理：从单帧到 Spritesheet

### 工具
| 工具 | 用途 | 平台 |
|------|------|------|
| **Aseprite** ($20) | 像素画编辑+动画 | Win/Mac/Linux |
| **Piskel** (免费) | 在线像素画编辑器 | 浏览器 |
| **LibreSprite** (免费) | Aseprite 开源分支 | Win/Mac/Linux |
| **TexturePacker** | 自动拼接 spritesheet | Win/Mac |
| **GIMP** (免费) | 通用图片编辑 | 全平台 |

### 工作流

```
1. AI 生成单帧图片（每个状态/姿势一张）
       ↓
2. 在 Aseprite/GIMP 中统一画布大小（如 128×128）
       ↓
3. 去除背景（魔棒工具 / 颜色选择删除）
       ↓
4. 手动微调像素对齐（确保帧间角色位置一致）
       ↓
5. 横向拼接成 spritesheet 网格
       ↓
6. 导出 PNG（保留透明通道）
```

### Spritesheet 规格（我们项目需要的）

| 素材 | 帧数 | 单帧尺寸 | 网格排列 | 总尺寸 |
|------|------|---------|---------|--------|
| 执行人-idle | 6帧 | 128×128 | 6×1 | 768×128 |
| 执行人-typing | 12帧 | 230×144 | 6×2 | 1380×288 |
| 监督人-idle | 6帧 | 128×128 | 6×1 | 768×128 |
| 监督人-reviewing | 12帧 | 230×144 | 6×2 | 1380×288 |
| 办公室背景 | 1帧 | 1280×400 | 1×1 | 1280×400 |

---

## 快速起步路线（推荐）

**最省时间的路径：**

1. **ChatGPT 生成 4 张角色单帧**（idle/typing/reviewing/celebrate）
   - 每个角色对话迭代 2-3 轮确保风格一致
   - 约 20 分钟

2. **Midjourney 生成 1 张办公室背景**
   - 用上面的 prompt，选最好的一张
   - 约 10 分钟

3. **Piskel (免费在线工具) 拼接 spritesheet**
   - https://www.piskelapp.com/
   - 导入帧 → 调整 → 导出 spritesheet PNG
   - 约 30 分钟

4. **总计约 1 小时**可以出一套基础素材

---

## 参考资源

- **Piskel 在线编辑器**: https://www.piskelapp.com/
- **Aseprite 官网**: https://www.aseprite.org/
- **CivitAI 像素 LoRA**: https://civitai.com/tag/pixel+art
- **LimeZu 免费素材**: https://limezu.itch.io/ （非商用可直接用）
- **OpenGameArt**: https://opengameart.org/ （大量免费游戏素材）
- **Star-Office 素材参考**: https://github.com/ringhyacinth/Star-Office-UI/tree/master/frontend
