@echo off
rem PENUMBRA.AI - website only. No Python needed; the app runs in demo mode with real in-browser encryption.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -WebsiteOnly
