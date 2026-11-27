@echo off
cd /d "%~dp0"
echo ====================================================
echo  SverkaSmet Web (SmartMatcher)
echo  URL: http://127.0.0.1:5000
echo ====================================================

if not exist ".env" (
    echo [ERROR] Файл .env не найден.
    echo Скопируйте .env.example в .env и укажите DB_PASS
    pause
    exit /b 1
)

python -c "import psycopg2" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Не установлена библиотека psycopg2 или зависимости проекта.
    echo Выполните: pip install -r requirements.txt
    pause
    exit /b 1
)

python web\web_app.py
pause
