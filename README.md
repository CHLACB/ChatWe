# 微信 AI 自动回复系统核心骨架

这是一个**架构优先**的项目骨架，用于替代“后端调用第三方 wxautox4 HTTP API”的旧模式。

目标结构：

```text
前端 / 外部程序
↓
本项目 FastAPI API
↓
应用服务层
↓
监听调度 / 消息入库 / 上下文构建 / AI网关 / 发送队列
↓
微信执行层 UIA / 本地历史消息读取层
```

## 当前版本原则

1. 不调用第三方 wxautox4 HTTP API。
2. 不猜测微信控件信息。
3. 已验证的微信 3.9.12.56 主窗口类名候选 `WeChatMainWndForPC` 可以作为版本专用策略；搜索框、输入框、消息区等未知控件仍必须本机采集。
4. 历史读取不猜测微信数据库结构，默认提供“标准化 SQLite 历史库”适配器。
5. 第一阶段只支持文本。
6. 当前只回复监听名单内的好友私聊，群聊暂不支持。
7. 自己消息入库，但不触发 AI。
8. 自动发送，但必须经过发送队列和会话验证。

## 文件结构概览

```text
src/wx_ai_assistant/
  api/                 FastAPI 路由层
  application/         应用服务、监听调度、发送队列、上下文构建
  core/                配置、异常、通用响应
  domain/              领域模型和枚举
  identity/            会话身份验证、防串聊、防错发
  infrastructure/      SQLite、UIA、历史读取、AI实现
  ports/               抽象接口，隔离具体实现
scripts/
  dump_wechat_controls.py   本机控件树采集脚本
docs/
  REQUIREMENTS.md
  ARCHITECTURE.md
  UIA_INSPECTION.md
  HISTORY_READER.md
  RUNBOOK.md
  KNOWN_LIMITS.md
config/
  app.example.yaml
  wechat_locators.example.json
```

## 本地运行：Mock 模式

Mock 模式不操作微信，可以用于验证 API、分层、入库、发送队列主链路。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn wx_ai_assistant.main:app --reload
```

默认 `APP_DRIVER_MODE=mock`。

打开：

```text
http://127.0.0.1:8000/docs
```

## 真实微信 UIA 模式

程序内置微信 PC 版 3.9.12.56 的通用 UIA 策略。多数环境可以先直接自检：

```bash
python scripts/wechat_uia_selfcheck.py 文件传输助手
```

自检通过后设置：

```text
APP_DRIVER_MODE=uia
```

如果自检失败，再采集控件信息并创建本机覆盖配置。

```bash
pip install uiautomation pywin32
python scripts/dump_wechat_controls.py --list-windows
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 8 --out docs/wechat_main_dump.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 10 --out docs/wechat_current_chat_dump.md
```

根据采集结果填写：

```text
config/wechat_locators.local.json
```

再设置：

```text
APP_DRIVER_MODE=uia
APP_WECHAT_LOCATORS=config/wechat_locators.local.json
```

注意：`.local.json` 只用于本机覆盖，不要提交。UIA 驱动会先使用内置 3.9.12.56 策略，再合并 local 覆盖。定位失败时会返回结构化错误和 dump 命令，而不是乱点窗口。

## Windows 打包分发

生成可分发 zip：

```powershell
.\scripts\package_windows.ps1
```

产物：

```text
dist\ChatWe-windows.zip
```

新机器解压后先运行：

```bat
selfcheck_uia.bat 文件传输助手
```

详见 `docs\PACKAGING.md`。

## Mock 主链路

Mock 模式可通过 API 跑通：

```text
POST /listen/targets
POST /messages/mock/text
GET  /messages/{conversation_id}
POST /send/text
```

`APP_AI_MODE=echo` 时，对方文本消息会生成 echo 回复并进入发送队列。发送队列串行执行，发送成功后会把自己消息入库，但自己消息不会再次触发 AI。

## LangGraph AI 网关

真实 AI 通过 `AiGateway` 接口接入，不会直接操作微信。默认推荐 `APP_AI_MODE=langgraph`：内部使用 LangGraph 拆成“意图分析 -> 是否回复 -> 回复策略 -> 草稿 -> 自动安全检查 -> JSON 输出”，外部仍然只返回兼容 `AiTurnParser` 的 JSON。

```text
APP_AI_MODE=langgraph
APP_AI_CONFIG=./config/ai.local.env
```

把示例文件复制为本机密钥文件：

```powershell
copy config\ai.local.example.env config\ai.local.env
notepad config\ai.local.env
```

填入：

```text
APP_AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
APP_AI_API_KEY=你的百炼APIKey
APP_AI_MODEL=deepseek-v4-flash
```

`config\ai.local.env` 已被 `.gitignore` 忽略，不要提交密钥。AI 返回空消息数组时不会创建发送任务；非空文本只会进入发送队列。旧的 `APP_AI_MODE=openai_compatible` 仍保留为回退模式。

AI 对话提示词独立放在：

```text
config/prompts/system.core.md
config/prompts/system.wechat_turn.md
config/prompts/styles/natural_short.md
```

`system.core.md` 是最高优先级系统提示词；`system.wechat_turn.md` 是微信回合协议；`styles/natural_short.md` 是说话风格。

默认是被动回合制：对方发来新消息后，LangGraph 只输出本轮回复，输出 `done=true` 后停止，等待对方下一条消息。最终必须用 JSON 决定要发几条微信消息：

```json
{"messages":["短句一","短句二"],"done":true}
```

程序不会按标点硬拆大段话，只会原样发送 AI 在 `messages` 数组里给出的边界。需要允许适度主动追问时，把 `config\ai.local.env` 里的 `APP_AI_PROACTIVE_MODE=off` 改成 `on`，但一轮仍然只调用一次 AI，发完就停。

对方连续发送多条消息时，系统会先持续入库但不立刻调用 AI。默认最后一条对方消息后等待 5 秒，期间没有新消息才启动 AI：

```text
APP_AI_TURN_QUIET_SECONDS=5.0
APP_AI_DUPLICATE_GUARD_SECONDS=120.0
APP_DIAGNOSTICS_CONTEXT_CHARS=1200
```

`APP_AI_DUPLICATE_GUARD_SECONDS` 用来防止 UIA 控件位置变化后，把同一条旧消息误判成新消息再次触发 AI。系统还会只响应“当前可见快照里最后一条自己消息之后”的对方文本消息。

如果 AI 请求失败或输出异常，本轮会跳过并记录诊断，监听不会因此退出。

调试时可查看 `/system/diagnostics`，其中包含最近监听到的可见消息快照、pending AI 回合、最近一次 AI 输入尾部和模型原始输出。`APP_DIAGNOSTICS_CONTEXT_CHARS` 控制诊断里保留多少字符的上下文尾部。

常驻监听启动时默认会把上次遗留的 `pending/sending` 发送任务标记为失败，避免旧回复在重启后突然补发。确实要恢复旧任务时再加 `--resume-pending`。

## 真实好友自动回复回归

先打开微信并确认目标好友可搜索，然后运行：

```powershell
.\.conda\python.exe scripts\uia_friend_auto_reply_test.py "AAxc" --timeout 180
```

脚本会先做一次基线轮询，不回复旧消息。随后让该好友发一条新的文本消息，系统会走完整链路：可见消息读取 -> 入库 -> AI -> 发送队列 -> 微信发送 -> 自己消息入库。

持续监听不要用一次性回归脚本，使用：

```powershell
.\.conda\python.exe scripts\uia_friend_listener_run.py "AAxc" --ai-mode langgraph
```

或：

```powershell
.\scripts\start_friend_listener.ps1 -Target "AAxc"
```

它会持续运行，AI 回复和自己消息入库后继续等待对方下一条消息。

多监听对象时，启动基线完成后系统会先被动扫描左侧会话列表；只有检测到未读/新消息信号的目标才会切换会话。无新消息时不会反复抢前台、不会发送 Ctrl+F。

调试左侧会话列表未读信号：

```powershell
.\.conda\python.exe scripts\dump_conversation_list_items.py --out docs\conversation_list_items.current.json
```

轻量管理监听对象：

```powershell
.\.conda\python.exe scripts\manage_listen_targets.py list
.\.conda\python.exe scripts\manage_listen_targets.py add "AAxc" --local-id "AAxc" --start
.\.conda\python.exe scripts\manage_listen_targets.py stop conv_xxx
.\.conda\python.exe scripts\manage_listen_targets.py delete conv_xxx
```

长时间监听稳定性检查不会发送回复：

```powershell
.\.conda\python.exe scripts\uia_stability_watch.py "AAxc" --minutes 30 --interval 3
```

诊断 API：

```text
GET /system/diagnostics
```

## 历史消息读取

本项目不直接猜测微信本地数据库结构。默认提供标准化历史库读取器，要求你把已处理好的历史消息映射成以下表：

```sql
normalized_messages(
  raw_id TEXT PRIMARY KEY,
  conversation_local_id TEXT,
  sender_type TEXT,
  sender_name TEXT,
  msg_type TEXT,
  content TEXT,
  created_at TEXT
)
```

后续你可以写真实微信数据库适配器，只要实现 `HistoryReader` 接口即可。

## 推荐开发顺序

1. 先用 Mock 模式跑通 API 和主链路。
2. 用 `dump_wechat_controls.py` 采集微信控件树。
3. 填写 UIA locator 配置。
4. 先实现 `switch_conversation` 和 `get_current_conversation`。
5. 再实现 `read_visible_text_messages`。
6. 最后实现 `send_text`。
7. 历史库适配器单独开发，不和 UIA 混在一起。
