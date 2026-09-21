@echo off
setlocal
REM Run as the Windows user who installed RemoteDesk.
REM An old ProgramData / Task Scheduler installation requires Administrator.
set "FAILED=0"
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v RemoteDeskAgent >nul 2>&1
if not errorlevel 1 (
  reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v RemoteDeskAgent /f >nul 2>&1
  if errorlevel 1 set "FAILED=1"
)
if exist "%ProgramData%\RemoteDesk\agent.exe" (
  schtasks /end /tn "RemoteDeskAgent" >nul 2>&1
  schtasks /delete /tn "RemoteDeskAgent" /f >nul 2>&1
)
REM Only stop agents from RemoteDesk installation folders, not unrelated agent.exe apps.
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $targets=@((Join-Path $env:LOCALAPPDATA 'RemoteDesk\agent.exe'),(Join-Path $env:ProgramData 'RemoteDesk\agent.exe')); Get-Process -Name agent -ErrorAction SilentlyContinue | Where-Object { $_.Path -in $targets } | Stop-Process -Force; Start-Sleep -Milliseconds 800; foreach ($path in $targets) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } }"
if errorlevel 1 set "FAILED=1"
if "%FAILED%"=="1" (
  echo Removal did not finish. For an older installation, run this script as Administrator.
  pause
  exit /b 1
)
if exist "%LOCALAPPDATA%\RemoteDesk\arguments.json" del /q "%LOCALAPPDATA%\RemoteDesk\arguments.json"
echo RemoteDesk Agent removed. It will no longer start at sign-in.
echo Device identity and logs were kept in %%USERPROFILE%%\.remotedesk.
pause
