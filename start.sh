#!/bin/bash

echo "Checking virtual environment..."
export SSL_CERT_FILE=$(python3 -m certifi)
# Проверяем, существует ли папка venv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "Installing requirements..."
    source venv/bin/activate
    pip install -r requirements.txt
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Starting StarLabs XRPL_EXECUTOR..."
python3 main.py

# На macOS нет прямого аналога pause, но можно добавить ожидание ввода
read -p "Press Enter to exit..."
