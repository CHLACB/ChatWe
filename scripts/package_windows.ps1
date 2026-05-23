param(
    [string]$Python = ".\.conda\python.exe",
    [string]$OutDir = "dist\ChatWe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found: $Python"
}

& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller uiautomation pywin32
& $Python -m compileall src scripts tests
& $Python -m pytest

if (Test-Path -LiteralPath $OutDir) {
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutDir | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --name ChatWeApi `
    --paths src `
    --collect-submodules wx_ai_assistant `
    --add-data "config\app.example.yaml;config" `
    --add-data "config\wechat_locators.example.json;config" `
    --add-data "docs;docs" `
    src\wx_ai_assistant\main.py

Copy-Item -LiteralPath "dist\ChatWeApi" -Destination $OutDir -Recurse -Force
Copy-Item -LiteralPath "scripts" -Destination "$OutDir\scripts" -Recurse -Force
Copy-Item -LiteralPath "README.md" -Destination "$OutDir\README.md" -Force
Copy-Item -LiteralPath "AGENTS.md" -Destination "$OutDir\AGENTS.md" -Force

@"
@echo off
set APP_DRIVER_MODE=uia
set APP_WECHAT_LOCATORS=config\wechat_locators.local.json
ChatWeApi\ChatWeApi.exe
"@ | Set-Content -LiteralPath "$OutDir\start_api_uia.bat" -Encoding ASCII

@"
@echo off
set APP_DRIVER_MODE=mock
ChatWeApi\ChatWeApi.exe
"@ | Set-Content -LiteralPath "$OutDir\start_api_mock.bat" -Encoding ASCII

@"
@echo off
python scripts\wechat_uia_selfcheck.py %*
"@ | Set-Content -LiteralPath "$OutDir\selfcheck_uia.bat" -Encoding ASCII

Compress-Archive -LiteralPath $OutDir -DestinationPath "dist\ChatWe-windows.zip" -Force
Write-Host "Packaged: dist\ChatWe-windows.zip"
