@echo off
setlocal
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0scripts\install.py" %*
  exit /b
)
where python >nul 2>nul
if %errorlevel% equ 0 (
  python "%~dp0scripts\install.py" %*
  exit /b
)
echo Python 3.10+ is required. Install Python and run scripts\install.py.
exit /b 1
