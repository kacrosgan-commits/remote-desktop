@echo off
setlocal
pushd "%~dp0"
python build_windows.py
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" echo Build failed. Do not distribute old executables from dist.
popd
pause
exit /b %RESULT%
