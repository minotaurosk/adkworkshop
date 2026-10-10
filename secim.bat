@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Eser secim araci aciliyor... (kapatmak icin bu pencereyi kapat)
python secim.py
pause
