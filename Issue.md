# 问题反馈与性能优化计划

## 原始问题反馈

- 聊天界面提出需求后，推荐歌曲需要几分钟才返回。等待期间可以用更自然的串场反馈缓解空等。
- 需要避免多个请求同时发出并逐一返回，当前应一次只处理一个请求。
- 用户指定歌手时，推荐结果应更严格贴近该歌手或需求。
- 一次推荐数量需要更合理，候选不足时只推荐相关歌曲即可。
- Agent 回复不要中英文混杂，不要每次都重复城市、天气等信息。
- 聊天框中的配置问题提示需要可关闭。
- 用户提出需求后，返回前应禁用继续输入，或后续提供中断/重新提需求能力。
- 等待响应时显示“电台正在回应”等动态状态。
- 修改缓存数据的路径，目前似乎是在C:\Users\Acer.LAPTOP-7BIU564Q\AppData\Roaming\clownfishstudio-desktop，路径修改到项目根目录

## 当前性能结论

最近打包版日志显示，慢主要来自两个地方：

- 启动慢：portable exe 启动后先释放/启动本地 Python + FastAPI，约 11-13 秒后才创建窗口。
- 聊天慢：一次聊天会完整重生成电台，并串行调用多次 Agent。典型耗时约 140-150 秒。

最近一次聊天耗时拆分：

| 阶段 | 耗时 |
| --- | ---: |
| request planner Agent | 31.1s |
| 主节目 Agent | 80.1s |
| 生成问候 Agent | 19.8s |
| 聊天回复 Agent | 15.5s |
| 网易云搜索 | 2.8s |
| SQLite / session | < 0.1s |

SQLite 不是瓶颈，天气也不是主要耗时，但天气数据目前不准确，已先关闭天气获取链路。

## 已执行

- 关闭天气 provider：后端强制返回 `source=disabled`，不再调用 OpenWeather，也不再回退 mock 城市天气。
- 配置保存时清空 OpenWeather key，并让运行状态显示 weather `disabled`。
- 设置面板隐藏 OpenWeather 输入项，避免继续配置错误天气源。
- 打包版启动改为先创建窗口，再后台等待后端 ready，减少黑屏等待。
- 聊天完整重生成后复用本轮 Agent 问候作为回复，不再额外调用一次聊天回复 Agent。

## 后续优化步骤

### 1. 区分聊天意图

目标：普通聊天 5-15 秒内返回，只有明确要求换歌/换氛围时才重生成节目。

做法：

- 新增轻量意图判断：`chat_only`、`retune_program`、`song_request`、`config_help`。
- `chat_only` 只调用一次短回复 Agent，不刷新候选、不重生成整档节目。
- `retune_program` 和 `song_request` 才进入节目重生成。
- 保持 Agent-first：意图判断仍由 Agent 或模型结构化输出完成，规则只做安全兜底。

### 2. 合并 Agent 调用

目标：把一次重生成从 3-4 次模型调用降到 1-2 次。

做法：

- 让主节目 Agent 同时输出 `program`、`host_greeting`、`chat_reply`。
- `StationOrchestrator` 不再单独调用 `generate_greeting`。
- 点歌理解可以作为主 Agent 的结构化子字段，减少单独 request planner 调用。

### 3. 限制 prompt 和候选规模

目标：减少 DeepSeek 首 token 延迟和生成长度。

做法：

- 候选从 18-20 首降到 10-12 首，严格请求时允许更少。
- chat history 只传最近 4-6 条。
- candidate metadata 只传 Agent 需要的字段，去掉冗余 tags/source 说明。
- 节目结构控制在 1 个 block，少量 narration，减少输出 token。

### 4. 候选和网易云缓存

目标：网易云候选收集稳定在 1-3 秒。

做法：

- 用户偏好、每日推荐、歌单种子做 TTL 缓存。
- 针对相同 query 的搜索结果做短期缓存。
- 精确点歌时跳过偏好候选和播客候选，只搜目标歌曲/歌手。

### 5. 音频缓存异步化

目标：接口返回不被音频下载阻塞。

做法：

- `normalizeStationResponse` 不等待所有远程音频下载完成。
- 先返回原始播放 URL，后台缓存成功后再替换为本地 file URL。
- 对失败的音频缓存只记录 warning，不影响电台生成。

### 6. 打包形态优化

目标：冷启动明显低于当前 portable 自解压体验。

做法：

- 优先改为安装版或 unpacked 目录分发，减少每次从 portable exe 解压到 Temp。
- 后端 `.venv` 放在稳定资源目录，避免每次冷启动都走临时路径。
- 后续再评估把 FastAPI 后端打成独立常驻 sidecar。

### 7. 超时和兜底

目标：慢服务失败时可控，不让用户等两分钟后才看到错误。

做法：

- request planner 超时控制在 15-20 秒，失败后回退到 mock planner。
- 主节目 Agent 超时控制在 45-60 秒，失败后用最近 session 或 mock Agent 兜底。
- 修复 DeepSeek 返回空内容/非 JSON 时的 500，返回可恢复错误或 fallback。

## 验收指标

- 窗口首屏出现：冷启动 2 秒左右。
- 后端 ready：不阻塞首屏，可在状态栏提示。
- 普通聊天：5-15 秒。
- 需要重生成的聊天：30-60 秒。
- 初次生成：30-60 秒。
- 配置保存：不自动完整重生成，保存本身小于 2 秒。
