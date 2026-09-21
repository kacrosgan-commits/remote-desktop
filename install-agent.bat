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
  echo Installation failed. See the error dialog or %%USERPROFILE%%\.remotedesk\agent.log.
  pause
  exit /b 1
)
