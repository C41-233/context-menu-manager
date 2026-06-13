@echo off
cd /d "%~dp0"

REM ---- Auto-detect Git root ----
set "GIT_ROOT="
for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\GitForWindows" /v InstallPath 2^>nul') do set "GIT_ROOT=%%b"
if not defined GIT_ROOT for %%d in (
    "C:\Program Files\Git"
    "C:\Program Files (x86)\Git"
    "%LOCALAPPDATA%\Programs\Git"
) do if exist "%%~d\usr\bin\bash.exe" set "GIT_ROOT=%%~d"
if not defined GIT_ROOT (
    echo Git not found. Please install Git for Windows.
    pause
    exit /b 1
)

REM Use the real bash (usr/bin/bash.exe), not the stub (bin/bash.exe)
set "BASH=%GIT_ROOT%\usr\bin\bash.exe"
set "PATH=%GIT_ROOT%\usr\bin;%GIT_ROOT%\mingw64\bin;%GIT_ROOT%\cmd;%PATH%"
set "MSYSTEM=MINGW64"

"%BASH%" "%~dp0push.sh"
pause
