@echo off

REM ---- Auto-detect Git Bash ----
set "BASH="
rem 1) Try registry
for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\GitForWindows" /v InstallPath 2^>nul') do set "GIT_DIR=%%b"
if defined GIT_DIR if exist "%GIT_DIR%\bin\bash.exe" set "BASH=%GIT_DIR%\bin\bash.exe"
rem 2) Try common paths
if not defined BASH for %%d in (
    "C:\Program Files\Git"
    "C:\Program Files (x86)\Git"
    "%LOCALAPPDATA%\Programs\Git"
) do if exist "%%~d\bin\bash.exe" set "BASH=%%~d\bin\bash.exe"
rem 3) Try PATH
if not defined BASH for /f "delims=" %%a in ('where bash.exe 2^>nul') do set "BASH=%%a"
if not defined BASH (
    echo Git Bash not found. Please install Git for Windows.
    pause
    exit /b 1
)

REM ---- Run the companion bash script ----
"%BASH%" --login "%~dp0push.sh"
pause
