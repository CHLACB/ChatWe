# Media Recognition

第一阶段目标是让语音、图片、表情包先以“可读文本描述”进入现有主链路：

```text
UIA 可见消息读取
-> MessageIngestionService
-> MediaRecognitionService
-> Message 入库
-> ContextBuilder
-> LangGraph / openai_compatible
-> SendQueue
```

## 当前已实现

- `MessageType` 已扩展为 `text / image / sticker / voice / unsupported`。
- `messages` 表已增加 `media_path / media_mime_type / media_description` 字段。
- UIA 读取可见消息时，会对微信已经暴露的媒体标记做保守分类：
  - `[图片]` -> `image`
  - `[动画表情]` / `[表情]` -> `sticker`
  - `[语音]` / `语音消息` / `语音转文字...` -> `voice`
- 入库前会经过 `MediaRecognitionService`。
- 图片/表情包会优先使用 UIA `CaptureToImage` 把可见消息 item 保存到 `data/media/uia_visible/...png`，并写入 `media_path`。
- 当前没有可靠素材文件时，服务会生成明确占位文本，例如：
  - `[图片识别待补充] [图片]`
  - `[表情包识别待补充] [动画表情]`
  - `[语音转写待补充] [语音]`
- 这些占位文本会进入 AI 上下文，因此不会静默丢消息。
- 图片/表情包识别已预留独立 Vision AI 通道，不复用聊天回复模型。
- 语音识别已预留独立 Speech AI 通道，不复用聊天回复模型。
- 如果微信 UI 已暴露“语音转文字：...”文本，系统会直接写入 `[语音转写] ...`。
- 如果后续 UIA 或缓存探测拿到了可靠音频文件路径，系统会调用 Speech AI 的
  OpenAI-compatible `/audio/transcriptions` 接口转写。

## 独立图片 AI 配置

图片/表情包识别使用单独配置项，推荐写在 `config/ai.local.env`：

```env
APP_VISION_AI_ENABLED=true
APP_VISION_AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
APP_VISION_AI_API_KEY=你的视觉模型密钥
APP_VISION_AI_MODEL=qwen-vl-plus
APP_VISION_AI_TEMPERATURE=0.1
APP_VISION_AI_MAX_TOKENS=300
APP_VISION_AI_TIMEOUT_SECONDS=30
APP_VISION_AI_SYSTEM_PROMPT=你是微信图片和表情包识别器。只描述图片/表情包里能看见的内容、文字和表达的情绪。不要生成聊天回复。
APP_VISION_AI_EXTRA_BODY={"enable_thinking":false}
```

这个通道只负责把图片/表情包转成文本描述，例如：

```text
[表情包识别] 一只卡通猫摊手，表达无奈和开玩笑。
```

聊天回复仍然由 `APP_AI_MODE` 对应的系统 AI / LangGraph 决策完成。

## 独立语音 AI 配置

语音转写使用单独配置项，推荐写在 `config/ai.local.env`：

```env
APP_SPEECH_AI_ENABLED=true
APP_SPEECH_AI_BASE_URL=https://api.openai.com/v1
APP_SPEECH_AI_API_KEY=你的语音模型密钥
APP_SPEECH_AI_MODEL=gpt-4o-mini-transcribe
APP_SPEECH_AI_LANGUAGE=zh
APP_SPEECH_AI_TIMEOUT_SECONDS=30
APP_SPEECH_AI_PROMPT=这是一条微信语音消息，请转写为简体中文。
```

这个通道只负责把语音转成文本，例如：

```text
[语音转写] 我刚刚在路上，晚点回复你
```

聊天回复仍然由 `APP_AI_MODE` 对应的系统 AI / LangGraph 决策完成。

## 为什么不直接解密微信媒体缓存

微信 PC 媒体路径、图片缓存格式、语音 `.aud` / SILK 文件与账号环境和版本有关。未验证前直接读取缓存容易导致换号、换机器、微信升级后失效。当前项目原则是“未知先探测，验证后固化”，所以第一阶段先走可见消息和占位识别。

## 下一步推荐

### 图片和表情包

优先实现：可见消息矩形截图裁剪。

需要先确认图片/表情消息在本机微信 3.9.12.56 的 UIA 表现：

```powershell
cd "C:\Users\16234\Desktop\项目1\wechat_ai_core_skeleton"
.\.conda\python.exe scripts\dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 16 --out docs\wechat_media_message_dump.md
```

请在当前聊天窗口里准备：

- 一张图片消息
- 一个表情包
- 一条语音消息

需要反馈字段：

- `name`
- `control_type`
- `class_name`
- `automation_id`
- `bounding_rectangle`
- `depth`
- `children_count`
- 消息 item 的子节点结构

也可以用更聚焦的脚本直接输出当前可见消息 item：

```powershell
.\.conda\python.exe scripts\dump_visible_message_items.py --out docs\wechat_visible_media_items.json
```

这个脚本会输出每个可见消息的 `detected_message_type`、`detected_sender`、`bounding_rectangle` 和子节点摘要，适合验证图片、表情包、语音在当前微信版本里的 UIA 表现。

如果要同时验证截图是否可用：

```powershell
.\.conda\python.exe scripts\dump_visible_message_items.py --capture-media --out docs\wechat_visible_media_items.with_media.json
```

确认图片/表情包的 `ListItemControl` 或可裁剪区域后，可在 `UiaWechatDriver` 中保存截图到 `data/media/...`，再交给 `MediaRecognitionService`。

识别优先级：

1. OCR：RapidOCR，适合图片中文字。
2. VLM：OpenAI-compatible vision / Qwen-VL，适合图片内容和表情包语义。

### 语音

优先级：

1. 如果微信 UI 已显示“语音转文字”，直接读取该文本。
2. 如果没有转文字，再探测本机语音文件路径和格式。
3. 验证后可以接入 Speech AI 或 whisper.cpp / faster-whisper 做转写。

不要在未验证路径和格式前硬编码微信语音缓存路径。
