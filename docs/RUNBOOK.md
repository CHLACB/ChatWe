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

## 4. 启动监听

调用：

```text
POST /listen/targets/{conversation_id}/start
```

## 5. 手动发送文本

调用：

```text
POST /send/text
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
