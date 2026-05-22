@echo off
setlocal

set "PLUGIN_ROOT=%CLAUDE_PLUGIN_ROOT%"
if "%PLUGIN_ROOT%"=="" set "PLUGIN_ROOT=%~dp0.."

where python >nul 2>nul
if not errorlevel 1 (
  python "%PLUGIN_ROOT%\python\agent_loop\__main__.py" %*
  exit /b %errorlevel%
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%PLUGIN_ROOT%\python\agent_loop\__main__.py" %*
  exit /b %errorlevel%
)

echo agent-loop: Python 3.11+ is required on PATH 1>&2
exit /b 127
