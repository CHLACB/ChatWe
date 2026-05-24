@echo off
setlocal
cd /d "%~dp0\.."
set APP_DRIVER_MODE=uia
set APP_AI_MODE=openai_compatible
set APP_AI_CONFIG=.\config\ai.local.env
set APP_WECHAT_LOCATORS=.\config\wechat_locators.local.json
.\.conda\python.exe scripts\uia_friend_listener_run.py %*
