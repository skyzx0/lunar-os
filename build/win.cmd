@echo off
rem Convenience shim so the build works from cmd.exe as well as PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0win.ps1" %*
