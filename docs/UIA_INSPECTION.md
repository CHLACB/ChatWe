# 微信 UIA 控件信息采集指南

## 1. 为什么需要采集

微信窗口控件信息会因微信版本、Windows 版本、语言、缩放、登录状态、窗口布局而变化。

因此本项目只固化已经确认的信息：微信 PC 3.9.12.56 主窗口类名候选 `WeChatMainWndForPC`。其余控件仍不写死：

1. 搜索框控件。
2. 搜索结果 / 会话入口。
3. 聊天标题控件。
4. 消息列表控件。
5. 单条消息控件。
6. 输入框控件。

这些需要在你的本机环境中采集。

## 2. 推荐工具

### 2.1 Inspect.exe

Inspect.exe 是 Windows SDK 中的 UI Automation 检查工具。

用途：

1. 查看控件 Name。
2. 查看 ClassName。
3. 查看 AutomationId。
4. 查看 ControlType。
5. 查看 BoundingRectangle。
6. 查看父子控件层级。

### 2.2 Accessibility Insights for Windows

适合可视化查看 UIA 树。

### 2.3 项目自带脚本

```bash
python scripts/dump_wechat_controls.py --list-windows
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 8 --out docs/wechat_main_dump.md
```

如果微信标题不是“微信”，使用实际标题关键词。

## 3. 需要采集哪些控件

至少需要：

```text
1. 顶层微信窗口
2. 搜索框
3. 搜索结果 / 会话入口
4. 当前聊天标题
5. 消息列表区域
6. 单条消息项
7. 输入框
8. 发送行为：Enter 或发送按钮
```

## 4. 每个控件记录什么

建议记录：

```text
Name
control_type
class_name
automation_id
bounding_rectangle
depth
children_count
父级路径
同级序号 index
是否稳定
```

不要长期依赖 RuntimeId，因为 RuntimeId 可能随窗口刷新变化。

## 5. 如何填写 locator 配置

复制：

```text
config/wechat_locators.example.json
```

为：

```text
config/wechat_locators.local.json
```

然后填入采集到的选择器。

选择器优先级建议：

```text
AutomationId > ClassName + ControlType > Name + ControlType > 层级路径 + index > 坐标兜底
```

坐标只能作为最后兜底。

## 6. 局部 dump 命令

先全量 dump：

```bash
python scripts/dump_wechat_controls.py --list-windows
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 8 --out docs/wechat_main_dump.md
```

手动在微信里切到目标聊天后，dump 当前聊天窗口控件树：

```bash
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 10 --out docs/wechat_current_chat_dump.md
```

当 `config/wechat_locators.local.json` 已有初步 locator 后，可以 dump 局部：

```bash
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near chat_title --depth 5 --out docs/wechat_chat_title_nearby.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near search_box --depth 5 --out docs/wechat_search_box_nearby.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near input_box --depth 5 --out docs/wechat_input_box_nearby.md
python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near message_list --depth 5 --out docs/wechat_message_list_nearby.md
```

如果局部 dump 失败，说明 locator 还不够可靠，需要回到全量 dump 或 Inspect.exe。

## 7. 如何固化到 3.9.12.56 专用定位器

固化前必须记录：

```text
wechat_version: 3.9.12.56
verification_source: dump 文件路径 / Inspect.exe 截图 / Accessibility Insights 记录
fallback: 定位失败时 dump 哪个局部区域
```

写入 `config/wechat_locators.local.json` 时，优先使用 `automation_id`；没有时使用 `class_name + control_type`、`name_contains + control_type`。`index` 只能在前面字段已经能缩小候选范围后作为辅助，不能单独使用。

## 8. 验证流程

不要一开始实现全部功能。按这个顺序验证：

```text
1. 能找到微信主窗口
2. 能读取当前聊天标题
3. 能切换到指定会话
4. 能确认当前会话就是目标会话
5. 能读取可见文本消息
6. 能定位输入框
7. 能粘贴文本
8. 能发送
9. 能读取最后一条自己消息做发送后校验
```

## 9. 重要边界

如果某个控件在 UIA 树中不可见，不要立刻猜坐标。

先检查：

1. 微信窗口是否最小化。
2. 微信是否被遮挡。
3. DPI 缩放是否异常。
4. 是否需要管理员权限一致。
5. 控件是否只有滚动到可见区域才出现。
6. 是否需要切换到聊天页面。
