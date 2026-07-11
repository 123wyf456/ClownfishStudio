# AGENTS.md

Codex 在 `ClownfishStudio` 仓库开发时遵循本文件；若冲突，优先级为 `CLAUDE.md` > 本文件 > 其他历史文档。

## 项目定位

ClownfishStudio 是 `desktop/` Electron + React + TypeScript 桌面端，加 `server/` FastAPI + Pydantic + SQLAlchemy 本地后端的 Agent-First AI 电台。

当前不是移动端项目，也不是通用播放器。不要创建 `mobile/`，不要把推荐/模型逻辑放到桌面端。

## 最高原则

- 用户输入先交给 LLM 理解。
- 工具只提供事实、候选内容和播放能力。
- 后端负责编排上下文、状态、校验和安全边界，不替模型理解用户。
- 目标是可持续播放、可继续生长的电台，不是一次性推荐列表。
- 生产链路必须使用真实 LLM，不允许 `mock` provider 或预设陪聊回复；测试可显式注入 mock / fake。

## 模块边界

- `server/app/agents/`：构造 prompt、调用模型、处理结构化输出；播放型 item 必须引用真实 `candidate_id`。
- `server/app/services/`：组织工具调用、汇总 context、管理 session / playlist / persistence；不要过度解释用户输入。
- `server/app/tools/`：事实层，只负责搜索候选、读取历史/偏好、返回外部事实。
- `desktop/`：体验层，只负责展示、聊天交互、播放器控制、设置和本地桥接。

## 聊天与控制

除明确播放器控制命令（如 `暂停`、`继续`、`下一首`、`上一首`、`跳过`）外，默认让 LLM 判断聊天、调台、点歌、追问或多意图组合。

后端可以做 schema 校验、候选引用校验、去重、限流、持久化和外部失败报错；不要用硬编码情绪词典、关键词路由或预设话术替代 LLM。

## 数据与配置

- 配置从 runtime `.env` 读取。
- SQLite、生成音频、缓存等放在 runtime data 下。
- 不要把真实 API key 写进代码。
- 改配置先看 `server/app/core/config.py`。
- 改桌面运行路径先看 Electron runtime root 处理。

## 验证

后端改动至少运行：

```bash
cd server
pytest
ruff check .
```

桌面端改动至少运行：

```bash
cd desktop
npm run build
```

只改文档可以不跑全量测试，但要说明。

## 开发偏好

- Python 使用类型标注，输入输出走 Pydantic schema，API 路由保持薄。
- React 页面展示和数据逻辑分离，不在组件里散落推荐决策。
- 小步修改，不做无关重构。
- 文档以当前真实代码为准，不把未实现规划写成事实。
