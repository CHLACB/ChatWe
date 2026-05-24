$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$env:APP_DRIVER_MODE = if ($env:APP_DRIVER_MODE) { $env:APP_DRIVER_MODE } else { "uia" }
$env:APP_AI_MODE = if ($env:APP_AI_MODE) { $env:APP_AI_MODE } else { "langgraph" }
$env:APP_AI_CONFIG = if ($env:APP_AI_CONFIG) { $env:APP_AI_CONFIG } else { ".\config\ai.local.env" }
$env:APP_WECHAT_LOCATORS = if ($env:APP_WECHAT_LOCATORS) { $env:APP_WECHAT_LOCATORS } else { ".\config\wechat_locators.local.json" }

$url = "http://127.0.0.1:8000/admin"
Write-Host "Starting ChatWe local admin console..."
Write-Host "URL: $url"
Write-Host "Press Ctrl+C to stop."

Start-Process $url | Out-Null
.\.conda\python.exe -m uvicorn wx_ai_assistant.main:app --app-dir src --host 127.0.0.1 --port 8000
