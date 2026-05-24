param(
    [Parameter(Mandatory=$true)]
    [string[]]$Target,
    [string]$AiMode = "langgraph",
    [double]$Interval = 1.5,
    [double]$StatusInterval = 10,
    [switch]$ResumePending,
    [switch]$DebugTurns
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:APP_DRIVER_MODE = "uia"
$env:APP_AI_MODE = $AiMode
$env:APP_AI_CONFIG = ".\config\ai.local.env"
$env:APP_WECHAT_LOCATORS = ".\config\wechat_locators.local.json"
$extra = @()
if ($ResumePending) {
    $extra += "--resume-pending"
}
if ($DebugTurns) {
    $extra += "--debug-turns"
}
.\.conda\python.exe scripts\uia_friend_listener_run.py @Target --interval $Interval --status-interval $StatusInterval --ai-mode $AiMode @extra
