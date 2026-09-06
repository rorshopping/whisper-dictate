@echo off
rem Whisper Dictate - headless start (no console window stays open).
rem Uses pythonw.exe (windowless) + --headless (hides any console if one exists).
cd /d %~dp0
start "" /min .venv\Scripts\pythonw.exe launcher.py --headless
exit
