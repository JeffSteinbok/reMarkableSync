@echo off
REM Build script for creating Windows executables
REM This script builds self-contained executables for Windows using PyInstaller

echo ==================================================
echo RemarkableSync - Windows Build Script
echo ==================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.11 or higher.
    exit /b 1
)

REM Check if PyInstaller is installed
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

REM Install dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt

REM Clean previous builds
echo.
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo Building RemarkableBackup...
pyinstaller --clean remarkable_backup.spec

echo.
echo Building RemarkableConverter...
pyinstaller --clean hybrid_converter.spec

echo.
echo ==================================================
echo Build Complete!
echo ==================================================
echo.

echo Executables created:
if exist "dist\RemarkableBackup.exe" (
    echo   - dist\RemarkableBackup.exe
    for %%A in ("dist\RemarkableBackup.exe") do echo     Size: %%~zA bytes
)
if exist "dist\RemarkableConverter.exe" (
    echo   - dist\RemarkableConverter.exe
    for %%A in ("dist\RemarkableConverter.exe") do echo     Size: %%~zA bytes
)

echo.
echo To distribute:
echo   1. Test the executables: dist\RemarkableBackup.exe --help
echo   2. Create a ZIP file with the executables
echo   3. Share with users
echo.
echo Note: Windows may show a security warning on first run.
echo       Users should click "More info" and then "Run anyway"
