@echo off
chcp 65001 >nul
cd /d "%~dp0"
python build.py || (pause & exit /b 1)
echo.
echo Onizleme: http://127.0.0.1:8770/   (kapatmak icin bu pencereyi kapat)
start "" http://127.0.0.1:8770/
python -m http.server 8770 --bind 127.0.0.1 --directory docs
