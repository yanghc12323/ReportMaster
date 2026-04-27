@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title Report Master v0.7

echo.
echo ========================================
echo   Report Master v0.7 启动脚本
echo ========================================
echo.

echo [1/2] 检查Python环境...
set "PYTHON_CMD="

rem 优先使用项目虚拟环境，避免与系统 Python 冲突
if exist "%~dp0.venv\Scripts\python.exe" (
    call :check_python "%~dp0.venv\Scripts\python.exe"
    if !errorlevel! EQU 0 (
        set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    )
)

rem 再尝试当前 python 命令
if not defined PYTHON_CMD (
    call :check_python "python"
    if !errorlevel! EQU 0 (
        set "PYTHON_CMD=python"
    )
)

rem 若当前 python 不可用或依赖缺失，再扫描 where python 的候选解释器
if not defined PYTHON_CMD (
    for /f "delims=" %%p in ('where python 2^>nul') do (
        if not defined PYTHON_CMD (
            rem 忽略 Microsoft Store 代理解释器
            echo %%p | find /I "WindowsApps" >nul
            if errorlevel 1 (
                call :check_python "%%p"
                if !errorlevel! EQU 0 (
                    set "PYTHON_CMD=%%p"
                )
            )
        )
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] 未检测到可用的 Python 3.8+ 解释器
    echo 需要模块: flask / flask_socketio / flask_cors
    echo 请在目标解释器中执行：python -m pip install -r requirements.txt
    echo 你也可以手动运行：^<Python3路径^> backend\app.py
    pause
    exit /b 1
)

echo ✅ Python环境正常（^>=3.8）
echo.

if /i "%~1"=="--check" (
    echo ✅ 环境检查通过（--check），未启动服务
    exit /b 0
)

echo [2/2] 启动应用...
echo 后端服务将在 http://localhost:5000 启动
echo 浏览器将在服务就绪后自动打开应用界面
echo 当前版本：v0.7（审稿接收前持续迭代）
echo.
echo 提示：关闭此窗口将停止服务
echo ========================================
echo.

rem 等待健康检查可用后再打开浏览器，避免 localhost 拒绝连接
start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='http://localhost:5000/api/health'; for($i=0;$i -lt 90;$i++){ try { $res=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if($res.StatusCode -ge 200){ Start-Process 'http://localhost:5000'; exit 0 } } catch {} Start-Sleep -Seconds 1 }; Write-Host '[提示] 服务启动较慢，请稍后手动访问 http://localhost:5000'"
"%PYTHON_CMD%" backend\app.py
exit /b %errorlevel%

:check_python
set "_py_cmd=%~1"
"%_py_cmd%" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
exit /b %errorlevel%
