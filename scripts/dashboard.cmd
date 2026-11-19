@echo off
rem Live dashboard that follows the notebooks tracked runs (track.start / QCC_TRACK=1). Usage: scripts\dashboard.cmd [run-name] [--port 8765] [--no-open-browser]
setlocal
set PYTHONIOENCODING=utf-8
if "%QCC_PY%"=="" set "QCC_PY=python"
cd /d "%~dp0.."
"%QCC_PY%" -m quantcore_circuits.cli dashboard %*
