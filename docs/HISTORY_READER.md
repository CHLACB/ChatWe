# 本地历史消息读取设计

## 1. 原则

本项目不猜测微信真实数据库结构。

原因：

1. 微信版本不同，库结构可能不同。
2. 数据可能分库。
3. 加密、索引、字段含义需要你本机确认。
4. 直接把结构写死会导致后续维护困难。

## 2. 当前骨架提供的方式

当前提供标准化 SQLite 历史库读取器。

也就是说，你可以先把真实微信历史消息转换成统一表：

```sql
CREATE TABLE normalized_messages (
  raw_id TEXT PRIMARY KEY,
  conversation_local_id TEXT NOT NULL,
  sender_type TEXT NOT NULL,
  sender_name TEXT,
  msg_type TEXT NOT NULL,
  content TEXT,
  created_at TEXT NOT NULL
);
```

然后系统通过 `NormalizedSqliteHistoryReader` 读取。

## 3. 为什么这样设计

这样可以把复杂问题拆开：

```text
真实微信库解密 / 解析 / 版本适配
↓
转换为 normalized_messages
↓
主系统读取统一结构
```

主系统不关心底层微信库版本。

## 4. 后续真实适配器

后续可以新增：

```text
Wechat3HistoryReader
Wechat4HistoryReader
CustomExportHistoryReader
```

只要实现 `HistoryReader` 接口即可。

## 5. 失败策略

历史读取失败时：

```text
返回错误信息
不影响实时监听
不影响消息入库
不影响发送队列
```

当前上下文构建层会把历史读取失败写入上下文提示，但不会中断实时消息入库、AI 生成或发送任务创建。
