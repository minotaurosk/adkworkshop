@echo off
chcp 65001 >nul
cd /d "%~dp0"
python build.py || goto :err
git add -A docs site.json theme build.py || goto :err
git diff --cached --quiet && (echo Degisiklik yok, gonderilecek bir sey yok. & pause & exit /b 0)
git commit -q -m "Site guncellendi %date% %time:~0,5%" || goto :err
git push -q origin main || goto :err
echo.
echo Gonderildi. Site 1-2 dakika icinde guncellenir: https://adkworkshop.com
pause
exit /b 0
:err
echo.
echo HATA: yukaridaki mesaja bak.
pause
exit /b 1
