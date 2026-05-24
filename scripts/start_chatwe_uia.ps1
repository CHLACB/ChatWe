$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:APP_DRIVER_MODE = "uia"
$env:APP_AI_MODE = "openai_compatible"
$env:APP_AI_CONFIG = ".\config\ai.local.env"
$env:APP_WECHAT_LOCATORS = ".\config\wechat_locators.local.json"
.\.conda\python.exe -m uvicorn wx_ai_assistant.main:app --app-dir src --host 127.0.0.1 --port 8000
