# DESIGN.md

ClownfishStudio 的数据契约以 Agent-First 为核心：移动端提交设备上下文和用户状态，后端 tools 补充事实和候选内容，Agent 只能基于候选内容编排 `RadioProgram`。

## Backend Data Contracts

### DeviceContext

移动端采集的设备上下文。

- `local_time`: 设备本地时间，ISO datetime。
- `timezone`: IANA 时区，例如 `Asia/Shanghai`。
- `locale`: 系统语言区域，可选。
- `city_hint`: 用户或系统提供的城市提示，可选。
- `latitude` / `longitude`: 前台定位结果，可选。

### UserStateInput

用户当前听歌需求。

- `mood`: 当前心情，可选枚举。
- `energy_level`: 1 到 5，可选。
- `needs`: 用户选择的收听目标列表。
- `duration_minutes`: 期望节目时长，5 到 180 分钟。
- `free_text`: 用户自由输入。

### ContextSnapshot

Agent 生成节目时使用的上下文快照。

- `device_context`: 原始设备上下文。
- `user_state`: 原始用户状态。
- `weather`: 天气工具返回的结构化事实。
- `captured_at`: 快照生成时间。

### UserMusicMemory

用户音乐记忆，由导入数据、历史行为和反馈逐步更新。

- `user_id`: 用户标识。
- `favorite_genres`: 偏好风格。
- `favorite_artists`: 偏好艺人。
- `disliked_artists`: 明确不喜欢的艺人。
- `recent_candidate_ids`: 最近推荐过的候选内容。

### CandidateItem

工具返回的候选内容。Agent 只能从这里选择节目项。

- `candidate_id`: 候选内容唯一 ID。
- `content_type`: `music` 或 `podcast`。
- `title`: 标题。
- `creator`: 艺人、主播或节目创作者。
- `duration_seconds`: 时长，可选。
- `playback_url`: 第一版可使用 mock URL，可选。
- `tags`: 工具提供的标签，只作材料，不作固定推荐规则。
- `source`: 候选内容来源。

### RadioProgram

Agent 输出的结构化电台节目。

- `program_id`: 节目 ID。
- `title`: 节目标题。
- `summary`: 节目说明。
- `context_snapshot`: 生成时上下文。
- `blocks`: 节目区块列表。
- `total_duration_minutes`: 预计总时长。

### FeedbackEvent

用户反馈事件。

- `feedback_type`: `like`、`dislike`、`skip`、`too_familiar`、`want_more_like_this`、`less_like_this`。
- `program_id`: 关联节目。
- `item_id`: 关联节目项，可选。
- `candidate_id`: 关联候选内容，可选。
- `comment`: 用户补充文字，可选。

### FeedbackResponse

反馈接口响应。

- `feedback`: 已保存的反馈事件。
- `memory_update_hint`: 后端根据反馈生成的记忆更新提示。

## Validation Rules

- Agent 生成的音乐或播客节目项必须包含 `candidate_id`。
- 串场节目项必须包含 `narration_text`。
- schema 只做结构和边界校验，不做固定推荐判断。
- `too_familiar`、`skip`、`dislike`、`less_like_this` 会生成后续节目可读取的 avoidance hint。
