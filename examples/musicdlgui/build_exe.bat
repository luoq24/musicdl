@echo off
chcp 65001 >nul
title MusicDL GUI - 一键打包工具

echo ========================================
echo   MusicDL GUI 打包工具
echo   将应用打包为可执行的 EXE 文件
echo ========================================
echo.

:: 设置项目路径
set "PROJECT_ROOT=%~dp0.."
set "GUI_DIR=%~dp0"
set "DIST_DIR=%GUI_DIR%dist"
set "BUILD_DIR=%GUI_DIR%build"

:: 检查 Python 是否可用
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确保已安装 Python 并添加到环境变量
    pause
    exit /b 1
)

:: 安装 PyInstaller（如果未安装）
echo [1/4] 检查 PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo     正在安装 PyInstaller...
    pip install pyinstaller -q
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
) else (
    echo     ✓ PyInstaller 已安装
)

:: 安装项目依赖
echo.
echo [2/4] 安装项目依赖...
pip install -r "%GUI_DIR%requirements.txt" -q
if errorlevel 1 (
    echo [警告] 部分依赖安装失败，继续打包...
)

:: 清理旧的打包文件
echo.
echo [3/4] 清理旧文件...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%GUI_DIR%musicdlgui.spec" del /f "%GUI_DIR%musicdlgui.spec"
echo     ✓ 清理完成

:: 开始打包
echo.
echo [4/4] 开始打包...
echo     这可能需要几分钟时间，请耐心等待...
echo.

:: 执行 PyInstaller 打包命令
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "MusicDL" ^
    --icon "%GUI_DIR%icon.ico" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    --hidden-import=PyQt6 ^
    --hidden-import=PyQt6.QtCore ^
    --hidden-import=PyQt6.QtGui ^
    --hidden-import=PyQt6.QtWidgets ^
    --hidden-import=musicdl ^
    --add-data "%PROJECT_ROOT%\musicdl;musicdl" ^
    "%GUI_DIR%musicdlgui.py"

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo ========================================
echo   ✓ 打包成功！
echo ========================================
echo.
echo 输出位置: %DIST_DIR%\MusicDL.exe
echo.
echo 你可以将此 exe 文件分享给朋友使用
echo.

:: 询问是否打开输出文件夹
set /p OPEN_FOLDER="是否打开输出文件夹？(Y/N): "
if /i "%OPEN_FOLDER%"=="Y" (
    explorer "%DIST_DIR%"
)

pause
