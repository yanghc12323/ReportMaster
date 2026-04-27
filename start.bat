@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Report Master v0.6

echo.
echo ========================================
echo   Report Master v0.6 启动脚本
echo ========================================
echo.

echo [1/2] 检查Python环境...
set "PYTHON_CMD="

rem 先尝试当前 python 命令
call :check_python "python"
if !errorlevel! EQU 0 (
    set "PYTHON_CMD=python"
)

rem 若当前 python 不可用或版本不符合，再扫描 where python 的候选解释器
if not defined PYTHON_CMD (
    for /f "delims=" %%p in ('where python 2^>nul') do (
        if not defined PYTHON_CMD (
            call :check_python "%%p"
            if !errorlevel! EQU 0 (
                set "PYTHON_CMD=%%p"
            )
        )
    )
)

if not defined PYTHON_CMD (
    echo ❌ 未检测到 Python 3.8+ 解释器
    echo 请安装 Python 3.8+，并确保其可通过 PATH 访问
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
echo 浏览器将自动打开应用界面
echo 当前版本：v0.6（审稿接收前持续迭代）
echo.
echo 提示：关闭此窗口将停止服务
echo ========================================
echo.

start http://localhost:5000
"%PYTHON_CMD%" backend\app.py
exit /b %errorlevel%

:check_python
set "_py_cmd=%~1"
"%_py_cmd%" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
exit /b %errorlevel%
