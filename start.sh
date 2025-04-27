#!/bin/bash

# Абсолютный путь к директории, где лежит этот скрипт (и python-скрипт)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Путь к вашему виртуальному окружению (используем $HOME для домашней директории)
VENV_DIR="$HOME/venv_monad"

# Имя вашего Python-скрипта
PYTHON_SCRIPT="main.py" # <<< Убедитесь, что имя файла верное

# Проверка существования venv
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Ошибка: Виртуальное окружение не найдено или не содержит bin/activate по пути: $VENV_DIR"
    echo "Пожалуйста, создайте его: python3 -m venv $VENV_DIR"
    exit 1
fi

# Активация виртуального окружения
echo "Активация окружения: $VENV_DIR"
source "$VENV_DIR/bin/activate"

# Переход в директорию со скриптом (важно для относительных путей, хотя мы их минимизировали)
cd "$SCRIPT_DIR"

# Запуск Python-скрипта
echo "Запуск скрипта: Monad..."
# Используем python3, т.к. venv уже активирован и PATH настроен
python3 "$PYTHON_SCRIPT"

# Код завершения Python скрипта
EXIT_CODE=$?

echo "Скрипт завершил работу с кодом: $EXIT_CODE"

# Деактивация (необязательно, т.к. скрипт завершается, но хорошая практика)
# deactivate

exit $EXIT_CODE
