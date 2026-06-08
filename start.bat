@echo off
REM Waterdrop launcher (Windows) — double-click to start the app.
cd /d "%~dp0"
where py >nul 2>nul && (py launch.py & goto :eof)
python launch.py
