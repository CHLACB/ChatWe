# Windows 打包与分发

目标：生成一个可分发的 Windows 包，让使用者在微信 PC 版 3.9.12.56 已登录的情况下，尽量无需手工编辑 UIA 控件配置即可运行。

## 打包命令

在项目根目录执行：

```powershell
.\scripts\package_windows.ps1
```

产物：

```text
dist\ChatWe-windows.zip
```

## 分发包内容

- `ChatWeApi\ChatWeApi.exe`：FastAPI 应用可执行文件
- `start_api_mock.bat`：mock 模式启动
- `start_api_uia.bat`：真实 UIA 模式启动
- `selfcheck_uia.bat`：真实微信 UIA 自检入口
- `config\ai.local.env`：本机 AI 密钥配置，默认复制自示例，解压后填写
- `config\prompts\`：提示词库和风格库，可直接编辑
- `scripts\`：诊断脚本
- `docs\`：运行和求真文档

## 新环境首次使用

1. 安装并登录微信 PC 版 3.9.12.56。
2. 打开微信主窗口，不要停在登录页。
3. 解压 `ChatWe-windows.zip`。
4. 运行：

```bat
selfcheck_uia.bat 文件传输助手
```

启用真实 AI 前，打开并填写：

```bat
notepad config\ai.local.env
```

至少填写 `APP_AI_API_KEY`。默认配置使用百炼 OpenAI 兼容接口和 `deepseek-v4-flash`。

如果回复太长或太主动，优先修改：

```bat
notepad config\prompts\system.wechat_turn.md
notepad config\prompts\styles\natural_short.md
```

默认要求 AI 输出 `{"messages":[...],"done":true}`，由 AI 自己决定每条微信消息的边界，程序不会硬拆句。

自检会验证：

- 微信主窗口 `WeChatMainWndForPC`
- 左侧搜索框
- 当前聊天标题
- 消息列表
- 输入框
- 发送按钮
- `Ctrl+F` 是否能无鼠标聚焦搜索框
- 能否切换到目标会话
- 能否读取可见文本消息

## 内置策略

程序内置微信 3.9.12.56 的通用 UIA 策略：

- 主窗口类名：`WeChatMainWndForPC`
- 会话切换：`Ctrl+F` 聚焦搜索框，验证焦点后粘贴会话名并 Enter
- 文本发送：剪贴板粘贴到输入框，`Alt+S` 发送
- 标题定位：右侧聊天 header 区域的非空文本，排除时间格式和横跨消息区的大宽度文本
- 消息区定位：右侧消息 `ListControl`
- 输入区定位：右下 `EditControl`

这些规则不包含账号名、绝对坐标或具体控件层级。窗口位置、分辨率变化时按相对区域匹配。

## 什么时候需要 local 配置

多数 3.9.12.56 环境可以不创建 `config\wechat_locators.local.json`。如果自检失败，再从 `config\wechat_locators.example.json` 复制一份为 local 配置并只覆盖失败项。

```bat
copy config\wechat_locators.example.json config\wechat_locators.local.json
```

失败时按 `docs\UIA_INSPECTION.md` 采集控件树。不要把自己的 `.local.json`、dump 文件、数据库发到公开仓库。

## 已知限制

- 只验证微信 PC 版 3.9.12.56。
- 第一阶段只支持文本消息。
- 不支持微信 4.x 的 Qt/UOS 新架构。
- 群聊和同名联系人需要进一步身份验证策略，不能只靠显示名。
- 若微信快捷键被用户改掉，`Ctrl+F` 或 `Alt+S` 可能失败，需要在自检中暴露并重新配置。
