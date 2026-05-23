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
6. 只回复监听名单内的好友 / 群聊。
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

真实 UIA 模式需要你先采集控件信息。

```bash
pip install uiautomation pywin32
python scripts/dump_wechat_controls.py --list-windows
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 8 --out docs/wechat_main_dump.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 10 --out docs/wechat_current_chat_dump.md
```

然后根据采集结果填写：

```text
config/wechat_locators.local.json
```

再设置：

```text
APP_DRIVER_MODE=uia
APP_WECHAT_LOCATORS=config/wechat_locators.local.json
```

注意：当前驱动只固化微信 3.9.12.56 主窗口类名候选。没有填写搜索框、聊天标题、输入框、消息区等定位器时，UIA 驱动会返回结构化错误和 dump 命令，而不是乱点窗口。

## Mock 主链路

Mock 模式可通过 API 跑通：

```text
POST /listen/targets
POST /messages/mock/text
GET  /messages/{conversation_id}
POST /send/text
```

`APP_AI_MODE=echo` 时，对方文本消息会生成 echo 回复并进入发送队列。发送队列串行执行，发送成功后会把自己消息入库，但自己消息不会再次触发 AI。

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
