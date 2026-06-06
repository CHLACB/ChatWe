# 策略分析模块

这是一个独立的旁路模块，用来承接“策略分析 / 文档知识库 / 只分析不发送”的能力。

## 边界

当前模块不会：

1. 修改自动回复配置。
2. 创建发送任务。
3. 调用微信发送。
4. 改变现有 LangGraph 自动回复链路。

它只读取联系人、近期消息和策略知识库，输出分析结果。

## API

```text
POST /strategy-analysis/documents/text
POST /strategy-analysis/documents/upload
GET  /strategy-analysis/documents
GET  /strategy-analysis/documents/{document_id}
POST /strategy-analysis/documents/{document_id}/enable
POST /strategy-analysis/documents/{document_id}/disable
DELETE /strategy-analysis/documents/{document_id}
POST /strategy-analysis/documents/{document_id}/rebuild-index
POST /strategy-analysis/knowledge/search
GET  /strategy-analysis/contacts/{conversation_id}/settings
POST /strategy-analysis/contacts/{conversation_id}/settings
POST /strategy-analysis/conversations/{conversation_id}/analyze
```

## 文档知识库

第一版支持两种输入：

1. 文本粘贴：`POST /strategy-analysis/documents/text`
2. 文件上传：`POST /strategy-analysis/documents/upload`

上传接口使用 JSON + base64，避免额外依赖 multipart：

```json
{
  "filename": "聊天技巧全集（01）.docx",
  "title": "聊天技巧全集（01）",
  "knowledge_type": "默认",
  "tags": ["话术", "回复内容"],
  "content_base64": "..."
}
```

文本粘贴示例：

```json
{
  "title": "任意标题",
  "knowledge_type": "用户自定义标签，可不填",
  "tags": ["用户自定义标签"],
  "content": "原始文本内容"
}
```

系统会把文档切成 `strategy_knowledge_chunks`，并同步写入 AI 文档知识库向量索引。

当前不会猜测文档属于什么知识类型。`knowledge_type` 只保存用户传入值；缺省时保存为
`unlabeled`。系统不会根据“不要 / 策略 / 话术”等关键词自动归类。

当前切割不猜测知识类型，但会尊重可见结构。短文本原样保存为一个 chunk；长文本按章节标题、
段落和模型长度限制切割。
因为默认使用 `tongyi-embedding-vision-flash-2026-03-06`，单条文本上限是 1024 token，
切块会保持在较小窗口内，避免 embedding 入库失败：

```text
max_chars = 700
overlap = 80
```

PDF 解析会删除跨页重复的页眉页脚和常见 QQ / 公众号 / URL 噪声；章节标题会单独成块，
切 chunk 时不会把上一章尾部和下一章标题硬拼在一起。

当前解析能力：

```text
docx  标准库解析段落文本，忽略图片
pptx  标准库解析幻灯片文本框，忽略图片
txt/md  按 UTF-8 文本读取
pdf   使用 pypdf 解析文本层，扫描 PDF 不 OCR
```

每个 chunk 会保留来源位置，例如：

```text
docx:paragraph:16
pptx:slide:3
pdf:page:12
```

当前向量库是本地 SQLite 实现：

```text
strategy_knowledge_documents   原始文档
strategy_knowledge_chunks      文档切块
strategy_knowledge_vectors     chunk 向量索引
```

当前 embedding provider 是 DashScope Multimodal-Embedding HTTP API，默认模型：

```text
APP_EMBEDDING_MODEL=tongyi-embedding-vision-flash-2026-03-06
APP_EMBEDDING_DIMENSIONS=768
APP_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding
```

必须配置真实 API Key：

```text
APP_EMBEDDING_API_KEY=sk-...
```

如果没有 `APP_EMBEDDING_API_KEY`，会依次读取 `DASHSCOPE_API_KEY`、`APP_AI_API_KEY`。
现在已经取消本地 hash embedding；没有真实 embedding 服务时，文档入库、重建索引和知识检索会报错。

向量仍然存入 SQLite，并用余弦相似度检索。后续如果数据量变大，可以把 `StrategyVectorIndex`
换成 Chroma、Qdrant 或 pgvector。

检索方式是 hybrid：

```text
query
-> query embedding
-> strategy_knowledge_vectors 余弦相似度
-> 词法得分补充
-> 返回 matched_knowledge
```

返回结果会显示 `score`、`vector_score`、`lexical_score` 和 `score_source`。如果显示“跳过旧模型”
数量大于 0，说明数据库里还有旧 embedding 模型生成的向量，需要对文档重建索引。

当前实现的是第二个向量库：AI 文档知识库。第一个“每个联系人独立的长上下文消息向量库”还未实现，
后续应单独建 namespace / 表 / 索引，避免把聊天长期记忆和策略知识混在一起。

## 联系人启用

文档知识库默认不会影响联系人自动回复。联系人级设置默认：

```json
{
  "enabled": false,
  "document_ids": [],
  "tag_filters": []
}
```

开启后，后续自动回复链路才可以按联系人读取文档知识库。当前策略分析接口仍然全局检索 active 文档，
因为它是手动分析工具，不会发送消息。

## 会话策略分析

分析接口只使用已入库消息，不主动滚动微信窗口，不读取新消息，不发送回复。

分析逻辑由大模型完成。流程是：

```text
conversation_id
-> 读取最近消息
-> 用消息和用户 instruction 检索文档知识库
-> 把 matched_knowledge、聊天记录、用户要求一起发给策略分析大模型
-> 大模型输出 JSON 分析报告
```

如果没有配置 `APP_AI_API_KEY`，接口会返回错误，不会使用本地规则假装分析。

输出包含：

```text
intent
needs
relationship_signal
risks
suggested_strategy
reply_examples
matched_knowledge
no_send=true
```

联系人策略和联系人背景 / 会话画像功能已取消，因此本模块不再提供配置草稿接口。
