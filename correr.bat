@echo off
rem CostoPolitico en Windows: doble clic para correr todo.
rem Carga completa 2023-2026:  correr.bat -Completo
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0correr.ps1" %*
if errorlevel 1 pause
