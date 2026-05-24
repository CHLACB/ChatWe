@echo off
setlocal
cd /d "%~dp0\.."
if "%APP_DRIVER_MODE%"=="" set APP_DRIVER_MODE=uia
if "%APP_AI_MODE%"=="" set APP_AI_MODE=langgraph
if "%APP_AI_CONFIG%"=="" set APP_AI_CONFIG=.\config\ai.local.env
if "%APP_WECHAT_LOCATORS%"=="" set APP_WECHAT_LOCATORS=.\config\wechat_locators.local.json
echo Starting ChatWe local admin console...
echo URL: http://127.0.0.1:8000/admin
start "" "http://127.0.0.1:8000/admin"
.\.conda\python.exe -m uvicorn wx_ai_assistant.main:app --app-dir src --host 127.0.0.1 --port 8000
