# 运行手册

## 1. Mock 模式启动

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn wx_ai_assistant.main:app --reload
```

## 2. 初始化系统

访问 Swagger：

```text
http://127.0.0.1:8000/docs
```

调用：

```text
POST /system/initialize
GET  /system/status
GET  /system/current-conversation
```

## 3. 添加监听对象

调用：

```text
POST /listen/targets
```

示例：

```json
{
  "display_name": "文件传输助手",
  "conversation_type": "friend",
  "remark_name": "文件传输助手",
  "local_id": "filehelper"
}
```

第一阶段只支持好友私聊。`conversation_type=group` 会被 Service 层拒绝，API 返回 400。

## 4. 启动监听

调用：

```text
POST /listen/targets/{conversation_id}/start
POST /listen/poll-once
```

## 5. 手动发送文本

调用：

```text
POST /send/text
GET  /send/tasks
GET  /send/tasks/{send_task_id}
```

所有手动发送也只会创建发送任务，不会绕过发送队列。

## 5.1 诊断状态

调用：

```text
GET /system/diagnostics
```

返回当前 driver 状态、当前会话、监听对象、最近发送任务、每个监听对象最近消息，以及 AI 配置是否已填写。API 不返回密钥原文，只返回 `ai_api_key_configured=true/false`。

## 6. 创建 Mock 消息

Mock 模式下调用：

```text
POST /messages/mock/text
```

示例：

```json
{
  "conversation_id": "conv_xxx",
  "content": "你好",
  "sender_name": "friend"
}
```

`APP_AI_MODE=echo` 时会生成回复并创建发送任务；`APP_AI_MODE=dummy` 时 AI 返回空文本，不创建发送任务。

## 7. 切到 UIA 模式

1. 安装 Windows 依赖。
2. 采集控件树。
3. 填写 `config/wechat_locators.local.json`。
4. 修改 `.env`：

```text
APP_DRIVER_MODE=uia
APP_WECHAT_LOCATORS=./config/wechat_locators.local.json
```

5. 重启服务。

如果要启用千问/百炼 OpenAI 兼容 AI 网关：

```powershell
copy config\ai.local.example.env config\ai.local.env
notepad config\ai.local.env
```

填写 `APP_AI_API_KEY` 后设置：

```text
APP_AI_MODE=openai_compatible
APP_AI_CONFIG=./config/ai.local.env
APP_AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
APP_AI_MODEL=deepseek-v4-flash
```

提示词和风格可以独立修改：

```text
config/prompts/system.wechat_turn.md
config/prompts/styles/natural_short.md
```

最高优先级系统提示词：

```text
config/prompts/system.core.md
```

关键配置：

```text
APP_AI_PROMPT_PATH=./config/prompts/system.wechat_turn.md
APP_AI_STYLE_PATH=./config/prompts/styles/natural_short.md
APP_AI_PROACTIVE_MODE=off
APP_AI_MAX_MESSAGES_PER_TURN=3
APP_AI_STRICT_TURN_JSON=true
APP_AI_CORE_PROMPT_PATH=./config/prompts/system.core.md
```

默认 `APP_AI_PROACTIVE_MODE=off` 是被动模式：只回应对方刚发来的内容，本轮回复完就停。改成 `on` 后允许适度主动追问，但仍然只输出一次 `messages` 数组，不会一直自我续写。

AI 输出必须由模型自己决定微信消息边界：

```json
{"messages":["先这样","你看可以吗"],"done":true}
```

程序不会按标点拆分一大段；只会发送 `messages` 数组里的每个元素。`done=true` 表示本轮回复完成，系统等待对方下一条消息。

也可以直接运行：

```powershell
.\scripts\start_chatwe_uia.ps1
```

## 8. UIA 采集命令

```bash
python scripts/dump_wechat_controls.py --list-windows
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 8 --out docs/wechat_main_dump.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 10 --out docs/wechat_current_chat_dump.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near chat_title --depth 5 --out docs/wechat_chat_title_nearby.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near search_box --depth 5 --out docs/wechat_search_box_nearby.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near input_box --depth 5 --out docs/wechat_input_box_nearby.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near message_list --depth 5 --out docs/wechat_message_list_nearby.md
```

局部 `--near` 需要 `config/wechat_locators.local.json` 已经有初步 locator。失败时先用全量 dump 或 Inspect.exe 补字段。

## 9. 出错优先检查

```text
1. 当前是否为 mock/uia 模式
2. 微信是否运行
3. 微信是否登录
4. locator 文件是否存在
5. locator 是否能找到窗口
6. 当前微信是否被最小化
7. Python 和微信权限是否一致
8. 是否有多个同名好友/群聊
```

## 10. 检查命令

```bash
python -m compileall .
pytest
```

如果 Windows shell 提示找不到 `python` 或 `pytest`，先安装 Python 3.10+ 并执行：

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
```

## 11. 真实 UIA 回归验证

在微信 3.9.12.56 已登录并打开主窗口后，可以按顺序验证：

```bash
python scripts/wechat_uia_selfcheck.py 文件传输助手
python scripts/switch_filehelper_test.py
python scripts/read_visible_messages_test.py
python scripts/send_queue_uia_test.py "uia-regression-001"
python scripts/uia_listener_poll_once_test.py 文件传输助手 2
```

期望结果：

- `switch_filehelper_test.py` 返回 `switch_status.ok=True`
- `read_visible_messages_test.py` 能读取可见文本消息
- `send_queue_uia_test.py` 返回 `send_task_status=success`
- `uia_listener_poll_once_test.py` 保持 `listen_status=listening`
- 第一次监听轮询只建立可见消息基线，不触发 AI
- 文件传输助手内自己的消息应入库，但 `pending_send_tasks=0`
- 连续两次轮询时 `stored_message_counts` 不应增长，表示同一屏可见旧消息没有重复入库或重复触发

验证普通好友私聊时，把命令中的会话名换成目标好友名：

```bash
python scripts/uia_listener_poll_once_test.py AAxc 2
```

期望结果：

- 可见的自己消息为 `sender=self`
- 时间分隔或系统提示为 `sender=system`
- 好友私聊中剩余文本为 `sender=other`
- 首次轮询只建立基线，旧消息不会触发 AI；收到新好友文本后才会创建发送任务

## 12. 真实好友新消息自动回复

### 一次性回归测试

确认 `config\ai.local.env` 已填写密钥后运行：

```powershell
.\.conda\python.exe scripts\uia_friend_auto_reply_test.py "AAxc" --timeout 180
```

脚本流程：

1. 初始化真实 UIA driver。
2. 切到目标好友私聊。
3. 第一轮只做基线入库，不回复旧消息。
4. 等待该好友发来新的文本。
5. 通过 AI 网关生成最终回复文本。
6. 创建发送任务并由发送队列串行发送。
7. 发送后验证成功则自己消息入库。

如果只想验证链路不消耗真实模型额度：

```powershell
.\.conda\python.exe scripts\uia_friend_auto_reply_test.py "AAxc" --ai-mode echo
```

### 持续监听运行

一次性测试脚本成功回复一次后会退出。真正常驻运行请使用：

```powershell
.\.conda\python.exe scripts\uia_friend_listener_run.py "AAxc" --ai-mode openai_compatible --interval 1.5
```

启动时默认会清理上次残留的 `pending/sending` 发送任务，避免旧回复补发。需要恢复旧任务时显式加：

```powershell
.\.conda\python.exe scripts\uia_friend_listener_run.py "AAxc" --resume-pending
```

如果临时 UIA 切换失败或标题读取失败，常驻脚本默认会安全重试；重试期间不会读消息或发送消息。

调试短跑可以加：

```powershell
.\.conda\python.exe scripts\uia_friend_listener_run.py "AAxc" --ai-mode echo --max-seconds 20
```

或者用 PowerShell 包装脚本：

```powershell
.\scripts\start_friend_listener.ps1 -Target "AAxc"
```

也可以用 CMD 包装脚本：

```bat
scripts\start_friend_listener.cmd AAxc
```

持续监听脚本会：

1. 启动真实 UIA driver。
2. 启动发送队列后台 worker。
3. 启动监听 worker。
4. 第一轮只建立可见消息基线，不回复旧消息。
5. 对方每发来一条新文本，都执行 `入库 -> AI -> 发送队列 -> 发送后验证 -> 自己消息入库`。
6. 同一轮轮询中如果读到多条新对方消息，只调用一次 AI，以最后一条作为触发点，上下文里保留前面的消息。
7. AI 通过 `messages + done=true` 明确本轮完成；发送完这些消息后系统等待对方下一条消息。
8. 自己发送的消息会入库，但不会触发 AI。
9. 程序不会在一次回复后退出，按 `Ctrl+C` 才停止。

可以同时监听多个好友私聊：

```powershell
.\.conda\python.exe scripts\uia_friend_listener_run.py "AAxc" "文件传输助手" --ai-mode openai_compatible
```

## 13. 长时间稳定性检查

该脚本只监听和读取，不发送 AI 回复：

```powershell
.\.conda\python.exe scripts\uia_stability_watch.py "AAxc" --minutes 30 --interval 3
```

重点观察：

- 每轮 `status=listening`
- `current` 始终为目标好友
- `messages` 不异常归零
- 失败时输出 `stopped error=...`
