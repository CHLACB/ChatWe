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
