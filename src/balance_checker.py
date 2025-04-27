import asyncio
from web3 import AsyncWeb3, Web3
from web3.eth import AsyncEth
from web3.exceptions import InvalidAddress
from web3 import AsyncHTTPProvider
from loguru import logger
from tabulate import tabulate

# --- КОНФИГУРАЦИЯ ---
RPC_URL = "https://rpc.testnet.xrplevm.org"
NATIVE_TOKEN_SYMBOL = "WXRP"
NATIVE_TOKEN_DECIMALS = 18

# Словарь ERC20 токенов для проверки {СИМВОЛ: АДРЕС}
# Замените на нужные вам токены и их адреса
ERC20_TOKENS = {
    "RISE":   "0x0c28777DEebe4589e83EF2Dc7833354e6a0aFF85",
    "RIBBIT": "0x73ee7BC68d3f07CfcD68776512b7317FE57E1939",
    # "USDT": "0x...", # Добавьте другие токены сюда
    # "INVALID": "0xInvalidAddressHere123" # Пример для теста ошибок
}

# Минимальный ABI для ERC20 (одинаков для всех)
ERC20_MIN_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
]
# --- КОНЕЦ КОНФИГУРАЦИИ ---

# Импорты и начало функции ...

async def get_wallet_data(private_key: str, w3: AsyncWeb3, token_info: dict):
    """
    Асинхронно получает данные для одного кошелька: адрес, балансы (нативный + ERC20), nonce.
    'token_info' - словарь {symbol: {'contract': obj, 'decimals': int}}
    Возвращает словарь с данными или базовый словарь с ошибкой ключа.
    """
    try:
        account = w3.eth.account.from_key(private_key)
        address = account.address
    except Exception as e:
        # ... (обработка ошибки ключа без изменений) ...
        short_key = f"{private_key[:4]}...{private_key[-4:]}" if len(private_key) > 8 else private_key
        logger.error(f"Ошибка обработки приватного ключа {short_key}: {e}")
        error_data = {
            "key": short_key,
            "address": "Invalid Key",
            "native_balance": "N/A",
            "nonce": "N/A"
        }
        for symbol in token_info.keys():
             error_data[f"{symbol}_balance"] = "N/A"
        return error_data

    # Инициализация данных
    data = {
        "key": f"...{private_key[-4:]}",
        "address": address,
        "native_balance": "N/A",
        "nonce": "N/A"
    }
    for symbol in token_info.keys():
        data[f"{symbol}_balance"] = "N/A"

    # Получаем нативный баланс
    try:
        native_balance_wei = await w3.eth.get_balance(address)
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        # Конвертируем и форматируем в строку с 6 знаками после запятой
        native_float_balance = native_balance_wei / (10**NATIVE_TOKEN_DECIMALS)
        data["native_balance"] = f"{native_float_balance:.6f}" # Используем f-строку для форматирования
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
    except Exception as e:
        logger.error(f"Не удалось получить нативный баланс для {address}: {e}")
        data["native_balance"] = "Error"

    # Получаем балансы ERC20
    for symbol, info in token_info.items():
        if info['contract'] and info['decimals'] is not None:
            try:
                erc20_balance_raw = await info['contract'].functions.balanceOf(address).call()
                # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
                # Конвертируем и форматируем в строку с 6 знаками после запятой
                erc20_float_balance = erc20_balance_raw / (10**info['decimals'])
                data[f"{symbol}_balance"] = f"{erc20_float_balance:.6f}" # Используем f-строку
                # --- КОНЕЦ ИЗМЕНЕНИЯ ---
            except Exception as e:
                logger.error(f"Не удалось получить {symbol} баланс для {address}: {e}")
                data[f"{symbol}_balance"] = "Error"
        else:
             data[f"{symbol}_balance"] = "Skipped"

    # Получаем nonce (без изменений)
    try:
        nonce = await w3.eth.get_transaction_count(address)
        data["nonce"] = nonce
    except Exception as e:
        logger.error(f"Не удалось получить nonce для {address}: {e}")
        data["nonce"] = "Error"

    return data

# ... остальная часть файла balance_checker.py ...

async def check_balances(private_keys: list[str]):
    """
    Проверяет балансы (нативный + несколько ERC20) и nonce для списка ключей.
    """
    if not private_keys:
        logger.warning("Список приватных ключей пуст.")
        return
    if not ERC20_TOKENS:
         logger.warning("Словарь ERC20_TOKENS пуст. Будет проверен только нативный баланс и nonce.")
         # Можно продолжить или выйти: return

    logger.info(f"Подключение к RPC: {RPC_URL}...")
    w3 = AsyncWeb3(AsyncHTTPProvider(RPC_URL), modules={'eth': (AsyncEth,)})

    if not await w3.is_connected():
        logger.error(f"Не удалось подключиться к RPC: {RPC_URL}")
        return

    # --- Подготовка информации о токенах ---
    logger.info("Получение информации о настроенных ERC20 токенах...")
    token_info = {} # Словарь для хранения {'symbol': {'contract': obj, 'decimals': int}}
    configured_symbols = [] # Список символов, для которых удалось получить данные

    for symbol, address_str in ERC20_TOKENS.items():
        logger.info(f"-> Проверка токена: {symbol} ({address_str})")
        contract = None
        decimals = None
        try:
            address = Web3.to_checksum_address(address_str) # Проверка и преобразование адреса
            contract = w3.eth.contract(address=address, abi=ERC20_MIN_ABI)
            decimals = await contract.functions.decimals().call()
            logger.success(f"   {symbol}: Decimals = {decimals}")
            token_info[symbol] = {'contract': contract, 'decimals': decimals}
            configured_symbols.append(symbol) # Добавляем в список успешно настроенных
        except InvalidAddress:
             logger.error(f"   {symbol}: Некорректный адрес '{address_str}'. Токен будет пропущен.")
             token_info[symbol] = {'contract': None, 'decimals': None} # Помечаем как невалидный
        except Exception as e:
            logger.error(f"   {symbol}: Не удалось получить decimals или создать контракт: {e}. Токен будет пропущен.")
            token_info[symbol] = {'contract': None, 'decimals': None} # Помечаем как невалидный

    if not configured_symbols:
         logger.error("Не удалось получить информацию ни для одного ERC20 токена. Проверка балансов ERC20 невозможна.")
         # Можно решить выйти: return
    # --- Конец подготовки информации о токенах ---


    logger.info(f"Получение данных для {len(private_keys)} кошельков...")
    tasks = []
    for pk in private_keys:
        tasks.append(asyncio.create_task(get_wallet_data(pk, w3, token_info)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Формирование данных для таблицы ---
    wallet_data_list = []
    for i, res in enumerate(results):
        row_data = []
        if isinstance(res, Exception):
            short_key = f"{private_keys[i][:4]}...{private_keys[i][-4:]}" if len(private_keys[i]) > 8 else private_keys[i]
            logger.error(f"Ошибка при обработке ключа {short_key}: {res}")
            # Базовые данные с ошибкой
            row_data = [i + 1, short_key, "Error processing key", "N/A"]
            # Добавляем N/A для всех токенов
            row_data.extend(["N/A"] * len(configured_symbols))
            # Добавляем N/A для Nonce
            row_data.append("N/A")
            wallet_data_list.append(row_data)

        elif res: # Если get_wallet_data вернула словарь
            # Базовые данные
            row_data = [
                i + 1,
                res.get("key", "N/A"),
                res.get("address", "N/A"),
                res.get("native_balance", "N/A"),
            ]
            # Добавляем балансы ERC20 в правильном порядке
            for symbol in configured_symbols: # Используем список успешно настроенных
                 row_data.append(res.get(f"{symbol}_balance", "N/A"))
            # Добавляем Nonce
            row_data.append(res.get("nonce", "N/A"))
            wallet_data_list.append(row_data)
        else:
             short_key = f"{private_keys[i][:4]}...{private_keys[i][-4:]}" if len(private_keys[i]) > 8 else private_keys[i]
             logger.warning(f"Неожиданный результат для ключа {short_key}")
             # Заполняем строку значениями N/A
             row_data = [i + 1, short_key, "Unknown result", "N/A"]
             row_data.extend(["N/A"] * len(configured_symbols))
             row_data.append("N/A")
             wallet_data_list.append(row_data)


    # Динамическое формирование заголовков
    headers = ["#", "Key End", "Address", f"{NATIVE_TOKEN_SYMBOL} Bal"]
    headers.extend([f"{symbol} Bal" for symbol in configured_symbols]) # Добавляем заголовки токенов
    headers.append("Nonce")

    # Вывод таблицы
    try:
        table = tabulate(wallet_data_list, headers=headers, tablefmt="grid", numalign="left", stralign="left")
        print("\n" + table + "\n")
        logger.info("Проверка балансов завершена.")
    except Exception as e:
        logger.error(f"Ошибка при создании таблицы: {e}")
        for row in wallet_data_list:
            print(row)

# --- Пример использования ---
if __name__ == "__main__":
    logger.add("multi_balance_checker.log", rotation="10 MB")

    # ВАЖНО: Замените на свои ключи или используйте файл
    example_private_keys = [
        "", # Замените
        "", # Замените
        "invalid_key_format",
        "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", # Замените
    ]

    # Чтение из файла (опционально)
    # keys_file = 'data/private_keys.txt'
    # try:
    #     with open(keys_file, 'r') as f:
    #         private_keys_from_file = [line.strip() for line in f if line.strip()]
    #     logger.info(f"Загружено ключей из {keys_file}: {len(private_keys_from_file)}")
    #     keys_to_check = private_keys_from_file
    # except FileNotFoundError:
    #     logger.error(f"Файл с ключами не найден: {keys_file}. Используются ключи из примера.")
    #     keys_to_check = example_private_keys
    keys_to_check = example_private_keys # Пока используем пример

    print("Запуск проверки балансов (нативный + несколько ERC20)...")
    try:
        asyncio.run(check_balances(keys_to_check))
    except KeyboardInterrupt:
        print("\nПроверка прервана пользователем.")
    except Exception as global_error:
        logger.critical(f"Непредвиденная ошибка: {global_error}", exc_info=True) # Добавлено exc_info=True
        print(f"Произошла критическая ошибка: {global_error}")