@echo off
rem ============================================================================
rem  test-fresh.cmd -- double-click this to run the "clean profile" test.
rem
rem  WHY THIS FILE IS PURE ASCII (no Chinese):
rem    cmd.exe reads .cmd files using the system ANSI codepage (GBK on a
rem    Chinese Windows), NOT UTF-8. Chinese text saved as UTF-8 gets mangled
rem    into bytes that cmd.exe treats as commands, e.g.
rem        '??rem' is not recognized as an internal or external command
rem    (the mangled bytes also ate the leading "-" of -ExecutionPolicy).
rem    Keeping this file ASCII-only makes it immune to the codepage.
rem    The Chinese explanations live in test-fresh.ps1 (saved as UTF-8 with BOM)
rem    and in README.md.
rem
rem  Usage:  double-click, or run  tools\test-fresh.cmd
rem ============================================================================

setlocal
cd /d "%~dp0.."

rem Switch the console to UTF-8 so the PowerShell script's Chinese output
rem displays correctly. Without this you get mojibake in the checklist.
chcp 65001 >nul 2>nul

where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "tools\test-fresh.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "tools\test-fresh.ps1" %*
)

if %errorlevel% neq 0 (
  echo.
  echo   Failed to start. You can also run this directly:
  echo     pwsh -File tools\test-fresh.ps1
  echo.
  pause
)

endlocal
