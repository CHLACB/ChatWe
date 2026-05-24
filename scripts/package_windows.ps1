param(
    [string]$Python = ".\.conda\python.exe",
    [string]$OutDir = "dist\ChatWe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found: $Python"
}

New-Item -ItemType Directory -Path ".packaging_tmp" -Force | Out-Null
$env:TEMP = (Resolve-Path ".packaging_tmp").Path
$env:TMP = $env:TEMP

Invoke-Checked $Python @("-m", "pip", "install", "-r", "requirements.txt")
Invoke-Checked $Python @("-m", "pip", "install", "pyinstaller", "uiautomation", "pywin32")
Invoke-Checked $Python @("-m", "compileall", "src", "scripts", "tests")
Invoke-Checked $Python @("-m", "pytest", "-p", "no:cacheprovider", "--basetemp", ".packaging_tmp\pytest")

if (Test-Path -LiteralPath $OutDir) {
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutDir | Out-Null

$binaryArgs = @()
foreach ($dll in @("ffi.dll", "libbz2.dll", "libcrypto-3-x64.dll", "libexpat.dll", "liblzma.dll", "libssl-3-x64.dll", "sqlite3.dll")) {
    $path = Join-Path ".\.conda\Library\bin" $dll
    if (Test-Path -LiteralPath $path) {
        $fullPath = (Resolve-Path -LiteralPath $path).Path
        $binaryArgs += @("--add-binary", "$fullPath;.")
    }
}
foreach ($dll in @("UIAutomationClient_VC140_X64.dll", "UIAutomationClient_VC140_X86.dll")) {
    $path = Join-Path ".\.conda\Lib\site-packages\uiautomation\bin" $dll
    if (Test-Path -LiteralPath $path) {
        $fullPath = (Resolve-Path -LiteralPath $path).Path
        $binaryArgs += @("--add-binary", "$fullPath;uiautomation\bin")
    }
}

$appExample = (Resolve-Path -LiteralPath "config\app.example.yaml").Path
$locatorExample = (Resolve-Path -LiteralPath "config\wechat_locators.example.json").Path
$aiExample = (Resolve-Path -LiteralPath "config\ai.local.example.env").Path
$promptPath = (Resolve-Path -LiteralPath "config\prompts").Path
$docsPath = (Resolve-Path -LiteralPath "docs").Path

Invoke-Checked $Python (@(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", "ChatWe",
    "--distpath", "build\pyinstaller_dist",
    "--workpath", "build\pyinstaller_build",
    "--specpath", "build\pyinstaller_spec",
    "--paths", "src",
    "--collect-submodules", "wx_ai_assistant",
    "--add-data", "$appExample;config",
    "--add-data", "$locatorExample;config",
    "--add-data", "$aiExample;config",
    "--add-data", "$promptPath;config\prompts",
    "--add-data", "$docsPath;docs",
    "src\wx_ai_assistant\cli.py"
) + $binaryArgs)

Copy-Item -LiteralPath "build\pyinstaller_dist\ChatWe" -Destination "$OutDir\ChatWe" -Recurse -Force
Copy-Item -LiteralPath "scripts" -Destination "$OutDir\scripts" -Recurse -Force
Copy-Item -LiteralPath "README.md" -Destination "$OutDir\README.md" -Force
Copy-Item -LiteralPath "AGENTS.md" -Destination "$OutDir\AGENTS.md" -Force
New-Item -ItemType Directory -Path "$OutDir\config" -Force | Out-Null
Copy-Item -LiteralPath "config\prompts" -Destination "$OutDir\config\prompts" -Recurse -Force

@"
@echo off
set APP_DRIVER_MODE=uia
set APP_AI_MODE=langgraph
set APP_AI_CONFIG=config\ai.local.env
set APP_WECHAT_LOCATORS=config\wechat_locators.local.json
ChatWe\ChatWe.exe api
"@ | Set-Content -LiteralPath "$OutDir\start_api_uia.bat" -Encoding ASCII

Copy-Item -LiteralPath "config\ai.local.example.env" -Destination "$OutDir\config\ai.local.example.env" -Force
if (-not (Test-Path -LiteralPath "$OutDir\config\ai.local.env")) {
    Copy-Item -LiteralPath "config\ai.local.example.env" -Destination "$OutDir\config\ai.local.env" -Force
}

@"
@echo off
set APP_DRIVER_MODE=mock
ChatWe\ChatWe.exe api
"@ | Set-Content -LiteralPath "$OutDir\start_api_mock.bat" -Encoding ASCII

@"
@echo off
ChatWe\ChatWe.exe selfcheck %*
"@ | Set-Content -LiteralPath "$OutDir\selfcheck_uia.bat" -Encoding ASCII

Compress-Archive -LiteralPath $OutDir -DestinationPath "dist\ChatWe-windows.zip" -Force
Write-Host "Packaged: dist\ChatWe-windows.zip"
