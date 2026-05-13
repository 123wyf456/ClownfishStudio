# AGENTS.md

本文件用于指导 Codex 在 ClownfishStudio 仓库中进行开发。

## 1. 项目定位

ClownfishStudio 是一个 **Agent-First 移动端个人电台 App**，目标平台是 **iOS 和 Android**。

开发时必须牢记：

> Agent 是推荐大脑，工具提供事实和能力，移动端负责交互和播放，后端负责 Agent 运行、数据管理和工具编排。

本项目不应被实现成传统的“规则打分推荐系统 + LLM 文案生成器”。规则、数据库和检索工具只负责提供约束和材料，真正的场景理解、推荐方向判断、节目编排和推荐解释应由 Agent 主导。

## 2. 推荐仓库结构

```text
ClownfishStudio/
├─ README.md
├─ DESIGN.md
├─ AGENTS.md
├─ mobile/
│  ├─ app/
│  ├─ components/
│  ├─ features/
│  │  ├─ radio/
│  │  ├─ player/
│  │  ├─ feedback/
│  │  └─ notifications/
│  ├─ services/
│  ├─ store/
│  └─ package.json
├─ server/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ agents/
│  │  ├─ tools/
│  │  ├─ services/
│  │  ├─ db/
│  │  ├─ schemas/
│  │  └─ core/
│  ├─ scripts/
│  ├─ tests/
│  └─ pyproject.toml
└─ data/
   └─ mock/
```

## 3. 技术栈约束

### Mobile

- 使用 React Native + Expo + TypeScript。
- 状态管理优先使用 Zustand。
- 本地缓存优先使用 AsyncStorage，后续有复杂需求再引入 SQLite。
- 定位使用 Expo Location。
- 推送使用 Expo Notifications。
- 音频播放第一版可以先 mock 或使用 Expo Audio，后续再根据后台播放需求评估 React Native Track Player。

### Server

- 使用 Python + FastAPI。
- 请求/响应模型使用 Pydantic。
- 数据库 ORM 使用 SQLAlchemy。
- 第一版数据库使用 SQLite。
- 后续正式部署可切 PostgreSQL。
- 配置从 `.env` 读取，不要把密钥写进代码。

### Agent

- 第一版实现 `RadioAgentRuntime`，封装模型调用和工具调用。
- 使用结构化输出，保证返回 RadioProgram JSON。
- Agent 输出必须经过 schema 校验。
- Agent 不允许凭空编造歌曲、播客或播放链接。
- Agent 只能从 tools 返回的候选内容中选择推荐项。

## 4. 开发原则

### 通用原则

- 优先保证代码清晰、可测试、可扩展。
- 不要一次性实现过大的功能。
- 每次开发围绕一个清晰任务完成。
- 所有新增模块需要有明确边界。
- 不要把移动端、后端、Agent 逻辑混在一起。
- 不要过早优化。
- 不要一开始接入所有真实平台，先使用 mock tools 跑通闭环。

### Agent 相关原则

必须坚持：

```text
Agent 主导理解和推荐
工具提供事实和候选内容
规则只做约束和兜底
```

不要把推荐主逻辑写成大量硬编码规则。

允许写的规则：

- schema 校验；
- 候选内容数量限制；
- 防止推荐不存在内容；
- 防止重复推荐最近高频内容；
- 工具失败兜底；
- API 参数校验。

不建议写成固定推荐逻辑：

```text
雨天一定推荐慢歌
夜晚一定推荐轻音乐
疲惫一定推荐 ambient
```

这些判断应该交给 Agent 综合理解。

## 5. 后端开发任务顺序

### 任务 1：创建后端骨架

创建 FastAPI 项目结构：

```text
server/app/main.py
server/app/api/
server/app/core/config.py
server/app/core/logging.py
server/app/schemas/
server/app/agents/
server/app/tools/
server/app/db/
server/tests/
```

完成标准：

- `uvicorn app.main:app --reload` 可以启动；
- `/health` 返回正常；
- 有 `.env.example`；
- 有基础测试。

### 任务 2：实现 Pydantic schema

在 `server/app/schemas/` 中实现：

- DeviceContext
- UserStateInput
- ContextSnapshot
- UserMusicMemory
- CandidateItem
- ProgramItem
- ProgramBlock
- RadioProgram
- FeedbackEvent
- GenerateProgramRequest
- GenerateProgramResponse

要求：

- 类型清晰；
- 枚举清晰；
- 字段和 `DESIGN.md` 保持一致；
- 添加基础单元测试。

### 任务 3：实现 mock tools

在 `server/app/tools/` 中实现：

- weather_tool.py
- memory_tool.py
- history_tool.py
- music_search_tool.py
- podcast_search_tool.py
- program_tool.py
- feedback_tool.py

要求：

- 工具返回结构化数据；
- mock 数据从 `data/mock/*.json` 读取；
- 工具不做复杂推荐判断；
- 工具函数有类型标注；
- 添加测试。

### 任务 4：实现 Radio Agent Runtime

在 `server/app/agents/` 中实现：

```text
radio_agent.py
prompts.py
runtime.py
```

要求：

- 汇总 device_context、weather、user_state、memory、history、candidate_items；
- 调用模型生成 RadioProgram；
- 支持 mock 模型模式，便于无 API key 时开发；
- 输出必须通过 schema 校验；
- Agent 推荐内容必须来自候选内容。

### 任务 5：实现生成接口

实现：

```text
POST /api/programs/generate
```

要求：

- 接收 GenerateProgramRequest；
- 调用 Weather Tool；
- 调用 Memory Tool；
- 调用 History Tool；
- 调用 Music / Podcast Search Tool；
- 调用 Radio Agent；
- 保存节目；
- 返回 GenerateProgramResponse。

### 任务 6：实现反馈接口

实现：

```text
POST /api/feedback
```

要求：

- 保存用户反馈；
- 更新用户记忆或生成 memory update hint；
- 后续生成节目时能读取反馈影响。

## 6. 移动端开发任务顺序

### 任务 1：创建 Expo 项目

要求：

- 使用 TypeScript；
- 建立基础目录；
- 添加 API client；
- 添加环境变量配置；
- 能在 iOS / Android 模拟器或真机启动。

### 任务 2：实现首页

首页包括：

- 环境摘要；
- 心情选择；
- 需求选择；
- 时长选择；
- 自由文本输入；
- 生成电台按钮；
- 电台结果卡片。

### 任务 3：实现设备上下文采集

要求：

- 获取当前时间；
- 获取时区；
- 请求前台定位；
- 定位失败时允许继续使用本地时间和城市 hint。

### 任务 4：调用后端生成节目

要求：

- 构造 GenerateProgramRequest；
- 调用 `/api/programs/generate`；
- 展示 loading / error / success；
- 展示 RadioProgram。

### 任务 5：实现反馈按钮

反馈包括：

- like
- dislike
- skip
- too_familiar
- want_more_like_this
- less_like_this

## 7. 代码质量要求

### Python

- 使用类型标注。
- 使用 Pydantic schema 管理输入输出。
- 核心函数要有单元测试。
- 工具函数要可单独测试。
- 不要在 API 路由中堆积业务逻辑。
- 路由只负责接收请求和调用 service/runtime。

### TypeScript

- API response 要定义类型。
- 页面组件和业务逻辑分离。
- UI 组件尽量小而清晰。
- 不要把 API 调用直接散落在多个组件里。
- 错误状态和 loading 状态要处理。

## 8. 不要做的事情

第一版不要做：

- 不要同时接入多个音乐平台；
- 不要先做复杂播放器；
- 不要做 PC 端；
- 不要做复杂社交功能；
- 不要做复杂推荐打分系统；
- 不要把 Agent 降级成文案生成器；
- 不要让模型编造不存在的歌曲；
- 不要把 OpenAI API key 写入前端；
- 不要让移动端直接调用模型 API。

## 9. 每次开发完成后的检查

后端任务完成后运行：

```bash
pytest
```

如果配置了格式化和静态检查，运行：

```bash
ruff check .
ruff format .
```

移动端任务完成后运行：

```bash
npm run lint
npm run typecheck
```

如果项目脚本暂时不存在，应先补充脚本或在提交说明中明确说明。

## 10. Codex 执行方式建议

每次只执行一个明确任务。推荐顺序：

```text
1. server skeleton
2. schemas
3. mock tools
4. radio agent runtime
5. generate program API
6. feedback API
7. mobile skeleton
8. mobile home screen
9. mobile context collection
10. mobile program display
11. feedback loop
```

每完成一个任务，都应更新 README 或必要注释，说明当前能运行到哪一步。

Follow CLAUDE.md for all rules.

# UI / UX Design Rules — ClownfishStudio

---

# 1. 设计目标

ClownfishStudio 不是传统播放器。

界面目标：

* 像“深夜电台”
* 像“陪伴感”
* 像“有人在为你编排内容”

避免：

* 复杂功能堆叠
* 工具化界面
* Spotify 风格信息密度

用户打开 App 后应该：

> 不需要思考，只需要进入“此刻的电台”。

---

# 2. 整体设计风格

## 关键词

```text id="5w3k27"
沉浸感
柔和
深色
呼吸感
留白
低信息密度
```

---

## 推荐风格

* 深色背景
* 模糊渐变（gradient blur）
* 大卡片
* 柔和动画
* 慢节奏切换
* 少按钮

---

## 禁止事项

❌ 不允许复杂列表
❌ 不允许高密度信息流
❌ 不允许大量文字堆积
❌ 不允许传统播放器风格 UI
❌ 不允许复杂导航层级

---

# 3. 页面结构

系统只允许 3 个核心页面：

```text id="syxwot"
1. Radio（首页）
2. Player（播放页）
3. Chat（聊天页）
```

禁止继续增加复杂页面。

---

# 4. Radio 页面（核心）

## 页面目标

用户打开 App 后：

```text id="yslx7d"
立即进入“今天的电台”
```

---

## 页面内容

### 4.1 今日电台标题

例如：

```text id="tvg7e5"
东京雨夜缓冲电台
深夜慢速频道
周日晚间恢复模式
```

标题必须由 Agent 生成。

---

### 4.2 Agent 串场文案

例如：

```text id="jlwm9u"
今晚有点凉，我们把节奏放慢一点。
```

特点：

* 短
* 有情绪
* 有陪伴感

禁止：

❌ 长篇 AI 文案
❌ ChatGPT 风格解释

---

### 4.3 环境信息（弱展示）

显示：

```text id="yxuk2k"
时间
城市
天气
温度
```

例如：

```text id="v1xk20"
Tokyo · Rain · 18°C · 22:30
```

注意：

* 小字体
* 低强调
* 不能抢主视觉

---

### 4.4 节目结构卡片

展示当前节目：

```text id="9y5t6m"
放慢呼吸
夜间漂流
最后一段柔光
```

卡片：

* 大圆角
* 半透明
* 毛玻璃感

---

### 4.5 主按钮

只允许：

```text id="o7oj9g"
▶ Play
🔁 Regenerate
```

不要增加复杂控制。

---

# 5. Player 页面（重点）

## 页面目标

沉浸播放。

---

## 页面内容

### 5.1 当前内容

显示：

* 封面
* 标题
* 艺术家

---

### 5.2 播放控制

只保留：

```text id="j7z0mc"
上一首
播放/暂停
下一首
```

---

### 5.3 Agent 串场

播放 TTS 时：

显示：

```text id="z29w0d"
“接下来换一点更温暖的旋律。”
```

---

### 5.4 用户反馈（重要）

允许：

```text id="wyh42h"
❤️ 喜欢
⏭ 跳过
✨ 更多这种
```

禁止复杂评分系统。

---

# 6. Chat 页面

## 页面目标

用户可以“和电台聊天”。

---

## 输入示例

```text id="wzv1lk"
我现在有点累
想听安静一点
不要播客
来点雨夜感觉
```

---

## Agent 行为

Agent 必须：

* 理解需求
* 重新生成节目
* 改变后续 segment

---

## UI 风格

聊天必须：

* 极简
* 不像客服
* 不像 ChatGPT

更像：

```text id="wjlwmg"
“正在和电台交流”
```

---

# 7. 动画规则

动画必须：

```text id="y19t5n"
慢
柔和
低刺激
```

推荐：

* fade
* blur transition
* gradient movement

禁止：

❌ 高频动画
❌ 弹跳效果
❌ 游戏化效果

---

# 8. 色彩规则

推荐：

```text id="g2krx9"
深灰
黑色
蓝灰
暖橙
柔和紫色
```

避免：

```text id="jowcf7"
高饱和
纯白
纯黑
荧光色
```

---

# 9. 字体规则

推荐：

```text id="7f4gnr"
Inter
SF Pro
Noto Sans
```

特点：

* 简洁
* 现代
* 有呼吸感

---

# 10. 适配平台

必须：

* 适配 iOS / Android / Windows

---

# 11. 音频体验规则

音乐和 TTS 的切换必须：

```text id="az0azl"
平滑
低突兀
低延迟
```

建议：

* fade in/out
* 音量渐变

---

# 12. 核心体验原则（最高优先级）

ClownfishStudio 的体验必须始终围绕：

> “有人正在为你实时编排一档电台节目”

而不是：

❌ 音乐库
❌ 歌单管理器
❌ 搜索型播放器

---

# 13. UI 成功标准

用户打开 App 后：

* 能立刻感受到“电台氛围”
* 不需要思考操作
* 感觉内容是“为此刻生成”
* 感觉 Agent 在陪伴自己

---

# 14. 最终一句话

ClownfishStudio 的 UI 不是“功能界面”。

而是：

> 一个有陪伴感、有情绪氛围的 AI 电台空间。
