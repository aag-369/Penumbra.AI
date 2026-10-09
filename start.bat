@echo off
rem PENUMBRA.AI - double-click to run the website and the API on this computer.
rem First run installs everything (a few minutes). Later runs start in seconds.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
