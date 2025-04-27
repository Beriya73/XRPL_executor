from loguru import logger
import os
import asyncio
import platform # Для определения ОС
from termcolor import cprint # Уже импортировано

# --- Импорты ваших модулей ---
# Убедитесь, что пути импорта правильные относительно этого файла
try:
    from src.faucet import main as faucet_main # СИНХРОННАЯ функция
    from src.swap import main as swap_main     # АСИНХРОННАЯ функция
    from src.liquid import main as liquid_main # АСИНХРОННАЯ функция
    # !!! ДОБАВЛЕНО: Импортируем функцию проверки балансов
    # !!! Убедитесь, что файл называется balance_checker.py и находится в src
    # !!! или измените путь/имя файла соответственно
    from src.balance_checker import check_balances as run_balance_checker # АСИНХРОННАЯ функция
except ImportError as e:
     print(f"Ошибка импорта модуля: {e}")
     print("Убедитесь, что все необходимые файлы (faucet.py, swap.py, liquid.py, balance_checker.py) находятся в папке src.")
     exit()
# --- Конец импортов ---


# Настройка логирования
logger.add("app.log", rotation="10 MB", level="INFO") # Установим уровень INFO
version = 1.0 # Увеличим версию для отслеживания изменений

def clear_terminal():
    """Очищает экран терминала для Windows, Linux и macOS."""
    os_name = platform.system()
    if os_name == "Windows":
        os.system('cls')
    else: # Linux и macOS
        os.system('clear')

def read_file_lines(file_path):
    """Читает строки из файла, удаляя пустые и пробельные строки."""
    full_path = os.path.abspath(file_path) # Получаем полный путь
    if os.path.exists(full_path):
        try:
            with open(full_path, 'r') as file:
                lines = [line.strip() for line in file if line.strip()]
                logger.info(f"Успешно прочитано {len(lines)} строк из {full_path}")
                return lines
        except Exception as e:
            logger.error(f"Ошибка чтения файла {full_path}: {e}")
            print(f"Ошибка чтения файла {full_path}: {e}")
            return []
    else:
        logger.warning(f"Файл не найден: {full_path}")
        print(f"Предупреждение: Файл не найден: {full_path}")
        return []

# --- Функции выполнения модулей (без изменений) ---
async def execute_faucet_in_thread(private_key, proxy=None):
    key_short = f"...{private_key[-6:]}"
    try:
        logger.info(f"Запуск крана (в потоке) для ключа: {key_short}")
        faucet_result = await asyncio.to_thread(faucet_main, private_key, proxy)
        logger.info(f"Кран для ключа {key_short} завершен. Результат: {faucet_result}")
    except Exception as e:
        logger.exception(f"Ошибка в модуле Faucet (в потоке) для ключа {key_short}: {e}")
        cprint(f"Ошибка в модуле Faucet для ключа {key_short}, ошибка: {e}", 'red') # Используем cprint для ошибок

async def execute_other_modules(private_key, proxy=None):
    key_short = f"...{private_key[-6:]}"
    swap_success = False # Флаг успеха свапа
    try:
        logger.info(f"Запуск свапа для ключа: {key_short}")
        swap_result = await swap_main(private_key, proxy)
        logger.info(f"Свап для ключа {key_short} завершен. Результат: {swap_result}")
        # Предположим, swap_main возвращает True при успехе или объект receipt
        if swap_result:
             swap_success = True
    except Exception as e:
        logger.exception(f"Ошибка в модуле Swap для ключа {key_short}: {e}")
        cprint(f"Ошибка в модуле Swap для ключа {key_short}, ошибка: {e}", 'red')

    # Запускаем liquid только если swap был успешен (опционально)
    # Если нужно запускать liquid всегда, уберите 'if swap_success:'

    try:
        logger.info(f"Запуск добавления ликвидности для ключа: {key_short}")
        liquid_result = await liquid_main(private_key, proxy)
        logger.info(f"Добавление ликвидности для ключа {key_short} завершено. Результат: {liquid_result}")
    except Exception as e:
        logger.exception(f"Ошибка в модуле Liquid для ключа {key_short}: {e}")
        cprint(f"Error in Liquid module for private_key: {key_short}, error: {e}", 'red')



# --- Основная функция с обновленным меню ---
async def main():
    cprint(f"Welcome to the XRPL Executor! v{version}", 'cyan')

    # Указываем путь относительно текущего файла скрипта
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    private_keys_file = os.path.join(data_dir, 'private_keys.txt')
    proxies_file = os.path.join(data_dir, 'proxies.txt')

    private_keys = read_file_lines(private_keys_file)
    proxies = read_file_lines(proxies_file)

    if not private_keys:
        logger.error(f"Ошибка: Файл {private_keys_file} не найден или пуст.")
        cprint(f"Ошибка: Файл {private_keys_file} не найден или пуст.", 'red')
        return

    if not proxies:
        logger.info(f"Файл {proxies_file} не найден или пуст. Работаем без прокси.")
        proxies_to_use = [None]
    else:
        logger.info(f"Найдено {len(proxies)} прокси.")
        proxies_to_use = proxies

    while True:
        clear_terminal() # Очистка терминала перед показом меню
        cprint(f"--- XRPL Executor v{version} ---",'green', attrs=['bold'])
        cprint(f"Загружено ключей: {len(private_keys)}", 'light_yellow')
        cprint(f"Используется прокси: {'Да' if proxies else 'Нет'}", 'light_yellow')

        # --- Обновленное меню ---
        cprint("\nМеню:", 'green')
        print("1. Только модуль Faucet (Кран)")
        print("2. Модули Swap (Обмен) и Liquid (Ликвидность)")
        print("3. Проверить балансы кошельков") # <-- Новый пункт
        print("4. Выход")                     # <-- Старый пункт 3 стал 4

        cprint("\nВыберите действие:", 'light_green', end='')
        choice = input(" ")
        # --- Конец обновленного меню ---

        if choice == '1':
            logger.info("Выбран режим Faucet.")
            clear_terminal()
            cprint("--- Запуск режима Faucet ---", 'cyan')
            for i, private_key in enumerate(private_keys):
                # Выбор прокси по кругу
                proxy_index = i % len(proxies_to_use)
                proxy = proxies_to_use[proxy_index]
                log_proxy = proxy if proxy else 'Нет'

                cprint(f"\n[{i+1}/{len(private_keys)}] Ключ: ...{private_key[-6:]} | Прокси: {log_proxy}", 'yellow')
                logger.info(f"Обработка Faucet: Ключ {i+1}/{len(private_keys)}, Прокси: {log_proxy}")
                await execute_faucet_in_thread(private_key, proxy)
                cprint(f"Пауза...", 'dark_grey')
                await asyncio.sleep(2)
            logger.info("Режим Faucet завершен.")
            cprint("\n--- Режим Faucet завершен ---", 'cyan')
            input("Нажмите Enter для возврата в меню...")

        elif choice == '2':
            logger.info("Выбран режим Swap + Liquid.")
            clear_terminal()
            cprint("--- Запуск режима Swap + Liquid ---", 'cyan')
            for i, private_key in enumerate(private_keys):
                proxy_index = i % len(proxies_to_use)
                proxy = proxies_to_use[proxy_index]
                log_proxy = proxy if proxy else 'Нет'

                cprint(f"\n[{i+1}/{len(private_keys)}] Ключ: ...{private_key[-6:]} | Прокси: {log_proxy}", 'yellow')
                logger.info(f"Обработка Swap/Liquid: Ключ {i+1}/{len(private_keys)}, Прокси: {log_proxy}")
                await execute_other_modules(private_key, proxy)
                cprint(f"Пауза...", 'dark_grey')
                await asyncio.sleep(5)
            logger.info("Режим Swap + Liquid завершен.")
            cprint("\n--- Режим Swap + Liquid завершен ---", 'cyan')
            input("Нажмите Enter для возврата в меню...")

        # --- Новый обработчик для проверки балансов ---
        elif choice == '3':
            logger.info("Выбран режим проверки балансов.")
            clear_terminal()
            cprint("--- Запуск проверки балансов ---", 'cyan')
            try:
                # Вызываем импортированную функцию проверки балансов
                await run_balance_checker(private_keys)
            except NameError:
                 cprint("Ошибка: Функция 'run_balance_checker' не найдена. Убедитесь, что импорт прошел успешно.", 'red')
                 logger.error("Функция 'run_balance_checker' не импортирована.")
            except Exception as e:
                 cprint(f"Произошла ошибка во время проверки балансов: {e}", 'red')
                 logger.exception("Ошибка во время выполнения run_balance_checker:")

            # Пауза для просмотра результата
            cprint("\n--- Проверка балансов завершена ---", 'cyan')
            input("Нажмите Enter для возврата в меню...")
        # --- Конец нового обработчика ---

        elif choice == '4': # Не забываем изменить номер выхода
            cprint("Выход из программы.", 'magenta')
            break
        else:
            cprint("Неверный выбор. Пожалуйста, попробуйте снова.", 'red')
            input("Нажмите Enter для продолжения...")

if __name__ == "__main__":
    # Создаем папку data, если её нет
    data_folder = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(data_folder, exist_ok=True)
    # Создаем пустые файлы, если их нет, чтобы избежать ошибок чтения
    if not os.path.exists(os.path.join(data_folder, 'private_keys.txt')):
        with open(os.path.join(data_folder, 'private_keys.txt'), 'w') as f: pass
    if not os.path.exists(os.path.join(data_folder, 'proxies.txt')):
        with open(os.path.join(data_folder, 'proxies.txt'), 'w') as f: pass

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем.")
    except Exception as e:
        logger.critical(f"Критическая ошибка в главном потоке: {e}", exc_info=True)
        cprint(f"\nПроизошла критическая ошибка: {e}", 'red')