@echo off
chcp 65001 >nul
title 打包直播监控系统
setlocal enabledelayedexpansion

echo.
echo ╔════════════════════════════════════╗
echo ║     直播监控系统 — 打包分发    ║
echo ╚════════════════════════════════════╝
echo.

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
for %%I in ("%PROJECT_DIR%") do set "PROJECT_NAME=%%~nxI"
set "PARENT_DIR=%PROJECT_DIR%\.."
set "OUTPUT_ZIP=%PARENT_DIR%\%PROJECT_NAME%-分发包.zip"

echo [1/4] 清理运行时文件 ...
del /q "%PROJECT_DIR%\debug_*.log" 2>nul
del /q "%PROJECT_DIR%\违规记录_*.docx" 2>nul
del /q "%PROJECT_DIR%\*.jpg" 2>nul
del /q "%PROJECT_DIR%\fontlist-*.json" 2>nul
del /q "%PROJECT_DIR%\*.pyc" 2>nul
if exist "%PROJECT_DIR%\screenshots\*" del /q "%PROJECT_DIR%\screenshots\*" 2>nul
if exist "%PROJECT_DIR%\tmp\*" rmdir /s /q "%PROJECT_DIR%\tmp" 2>nul
if exist "%PROJECT_DIR%\tmp" mkdir "%PROJECT_DIR%\tmp"
if not exist "%PROJECT_DIR%\screenshots" mkdir "%PROJECT_DIR%\screenshots"
echo         done

echo [2/4] 删除旧打包文件 ...
if exist "%OUTPUT_ZIP%" del "%OUTPUT_ZIP%"
echo         done

echo [3/4] 正在打包 ...

powershell -NoProfile -Command "$source='%PROJECT_DIR%'; $dest='%OUTPUT_ZIP%'; if(Test-Path $dest){Remove-Item $dest -Force}; $excludeDirs=@('.venv','.git','.idea','.agents','.codex','node_modules','Lib','Scripts','Include','share','__pycache__'); $files=Get-ChildItem $source | Where-Object {$excludeDirs -notcontains $_.Name}; Compress-Archive -Path $files.FullName -DestinationPath $dest -CompressionLevel Optimal -Force; Write-Output 'done'"

if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ╔════════════════════════════════════╗
echo ║   done 打包完成！                ║
echo ║                                 ║
echo ║   %PROJECT_NAME%-分发包.zip
echo ╚════════════════════════════════════╝
echo.
echo 将分发包发给他人后，对方只需：
echo    1. 解压到任意目录
echo    2. 双击 setup.bat 配置环境
echo    3. 双击 启动监控.bat 开始使用
echo.
pause
