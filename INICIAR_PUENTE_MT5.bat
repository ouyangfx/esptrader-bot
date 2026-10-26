@echo off
title PUENTE LOCAL IQ OPTION - METATRADER 5
color 0A
cls
echo =====================================================================
echo           TRADER 4 LESS - PUENTE LOCAL IQ OPTION - MT5
echo =====================================================================
echo.
echo Iniciando transmision de ticks OTC directamente a MetaTrader 5...
echo No cierres esta ventana mientras uses MetaTrader 5.
echo.

cd /d "%~dp0"
if not exist "Local_OTC_Bridge.py" (
    cd /d "c:\Users\LAPTOP\Desktop\ESPTRADER"
)
py Local_OTC_Bridge.py
pause
