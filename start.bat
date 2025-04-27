@echo off
echo Checking virtual environment...

REM Проверка на существование виртуального окружения venv или .venv
if not exist venv (
    if not exist .venv (
        echo Creating virtual environment...
        python -m venv venv
        echo Installing requirements...
        call venv\Scripts\activate.bat
        pip install -r requirements.txt
    ) else (
        echo Virtual environment .venv already exists.
        call .venv\Scripts\activate.bat
    )
) else (
    echo Virtual environment venv already exists.
    call venv\Scripts\activate.bat
)
)



echo.
echo Starting StarLabs Xrpl Executor...
python main.py
pause
