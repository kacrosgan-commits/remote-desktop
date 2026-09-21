@echo off
setlocal
if not exist "%~dp0agent.exe" (
  echo ERROR: Put this script beside the newly built agent.exe.
  pause
  exit /b 1
)
REM Installs for the signed-in Windows user. No administrator rights needed.
"%~dp0agent.exe" --install
if errorlevel 1 (
  echo Installation failed.
  echo.
  echo Check the error dialog, or open:
  echo   %USERPROFILE%\.remotedesk\agent.log
  echo.
  echo If an old agent is stuck, run:
  echo   %LOCALAPPDATA%\RemoteDesk\uninstall-agent.bat
  echo then try again.
  pause
  exit /b 1
)
echo RemoteDesk Agent installed and starting in the background.
