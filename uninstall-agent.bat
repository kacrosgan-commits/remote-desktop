@echo off
setlocal
REM Run as the Windows user who installed Remote Dragon.
REM An old ProgramData / Task Scheduler installation requires Administrator.
set "FAILED=0"
REM Current + legacy (RemoteDesk) startup entries.
for %%V in (RemoteDragonAgent RemoteDeskAgent) do (
  reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v %%V >nul 2>&1
  if not errorlevel 1 (
    reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v %%V /f >nul 2>&1
    if errorlevel 1 set "FAILED=1"
  )
)
for %%T in (RemoteDragonAgent RemoteDeskAgent) do (
  schtasks /end /tn "%%T" >nul 2>&1
  schtasks /delete /tn "%%T" /f >nul 2>&1
)
if exist "%ProgramData%\RemoteDragon\agent.exe" (
  schtasks /end /tn "RemoteDragonAgent" >nul 2>&1
  schtasks /delete /tn "RemoteDragonAgent" /f >nul 2>&1
)
if exist "%ProgramData%\RemoteDesk\agent.exe" (
  schtasks /end /tn "RemoteDeskAgent" >nul 2>&1
  schtasks /delete /tn "RemoteDeskAgent" /f >nul 2>&1
)
REM Only stop agents from Remote Dragon / legacy RemoteDesk folders, not unrelated agent.exe apps.
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $targets=@((Join-Path $env:LOCALAPPDATA 'RemoteDragon\agent.exe'),(Join-Path $env:LOCALAPPDATA 'RemoteDesk\agent.exe'),(Join-Path $env:ProgramData 'RemoteDragon\agent.exe'),(Join-Path $env:ProgramData 'RemoteDesk\agent.exe')); Get-Process -Name agent -ErrorAction SilentlyContinue | Where-Object { $_.Path -in $targets } | Stop-Process -Force; Start-Sleep -Milliseconds 800; foreach ($path in $targets) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } }"
if errorlevel 1 set "FAILED=1"
if "%FAILED%"=="1" (
  echo Removal did not finish. For an older installation, run this script as Administrator.
  pause
  exit /b 1
)
if exist "%LOCALAPPDATA%\RemoteDragon\arguments.json" del /q "%LOCALAPPDATA%\RemoteDragon\arguments.json"
if exist "%LOCALAPPDATA%\RemoteDesk\arguments.json" del /q "%LOCALAPPDATA%\RemoteDesk\arguments.json"
echo Remote Dragon Agent removed. It will no longer start at sign-in.
echo Device identity and logs were kept in %%USERPROFILE%%\.remote-dragon
echo (or %%USERPROFILE%%\.remotedesk for older installs).
pause
