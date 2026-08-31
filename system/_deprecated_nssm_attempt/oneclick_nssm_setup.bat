@echo off
REM ============================================================
REM  One-click NSSM setup for KotakQuantService
REM  Created 2026-08-31 17:01 IST by Mavis
REM
REM  User action: double-click this file. UAC appears, click Yes.
REM  Script does the rest: installs the NSSM service and starts it.
REM
REM  Result: KotakQuantService runs as LocalSystem, auto-restarts
REM  on crash, survives reboots. True 24/7.
REM ============================================================

setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -Command "Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%SCRIPT_DIR%oneclick_nssm_setup.ps1' -Verb RunAs -WindowStyle Hidden"
endlocal
