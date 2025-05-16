import asyncio
import json
import os
import time
from random import randint
from loguru import logger
from .client import Client # Убедитесь, что класс Client импортирован правильно из вашего файла
from aiohttp import ClientSession


# 1. RPC URL для сети с Chain ID 1449000
RPC_URL = "https://rpc.testnet.xrplevm.org"
CHAIN_ID = 1449000
EXPLORER = "https://explorer.testnet.xrplevm.org/tx/"

# 2. Токены
# Важно: self.chain_token в классе Client должен быть установлен как WXRP_ADDRESS для add_liquidity_eth
WXRP_ADDRESS = "0x81Be083099c2C65b062378E74Fa8469644347BB7"
RISE_ADDRESS = "0x0c28777DEebe4589e83EF2Dc7833354e6a0aFF85"
RIBBIT_ADDRESS = "0x73ee7BC68d3f07CfcD68776512b7317FE57E1939"

# Контракты
ROUTER_ADDRESS = "0x25734cf60ca932A57A31984240DbF32215Fd96b7"
FACTORY_ADDRESS = "0x3f28f02d7534958f085D7E786B778D3C8E95c32c" # Не используется напрямую в add_liquidity, но может быть нужен роутеру

SLIPPAGE = 0.05  # 5%

abi_file_path = os.path.join(os.path.dirname(__file__), '..', 'abi', 'router.json')
try:
    with open(abi_file_path, 'r') as f:
        router_abi = json.load(f)
except FileNotFoundError:
    logger.error(f"ОШИБКА: Файл ABI '{abi_file_path}' не найден.")
    exit()
except json.JSONDecodeError:
    logger.error(f"ОШИБКА: Не удалось декодировать JSON из файла ABI '{abi_file_path}'.")
    exit()


# Словарь для сопоставления адресов токенов с их названиями
TOKEN_NAMES = {
    WXRP_ADDRESS: "WXRP",
    RISE_ADDRESS: "RISE",
    RIBBIT_ADDRESS: "RIBBIT"
}

class LiquidXRPL(Client):
    def __init__(self, private_key, proxy, rpc_url, explorer_url):
        super().__init__(private_key, proxy, rpc_url, explorer_url)
        # Важно: Убедитесь, что в базовом классе Client self.chain_token = WXRP_ADDRESS
        if not hasattr(self, 'chain_token') or self.chain_token != WXRP_ADDRESS:
             logger.warning(f"Атрибут self.chain_token не найден или не совпадает с WXRP_ADDRESS ({WXRP_ADDRESS}). Функция add_liquidity_eth может работать некорректно.")
             # Установим его здесь на всякий случай, но лучше это делать в базовом Client
             self.chain_token = WXRP_ADDRESS
        self.router_contract = self.get_contract(ROUTER_ADDRESS, abi=router_abi)

    @classmethod
    def simplify_wei_balance(cls, wei_balance: int) -> int:
        """
        Упрощает баланс в Wei (большое целое число), сохраняя первые две
        значащие цифры и заменяя остальные нулями.
        Использует метод манипуляции со строками и выполняет отсечение (truncation),
        а не математическое округление.
        """
        if wei_balance is None: return 0 # Обработка None
        wei_balance = int(wei_balance) # Преобразуем на всякий случай

        if wei_balance == 0:
            return 0

        s = str(wei_balance)
        length = len(s)

        if length <= 2:
            return wei_balance
        else:
            first_two_digits = s[:2]
            simplified_str = first_two_digits + '0' * (length - 2)
            return int(simplified_str)

    async def get_reserves_from_pool(self, tokenA_address: str, tokenB_address: str, stable: bool):
        """
        Получает резервы, десятичные знаки и отсортированные адреса для пары токенов.
        Возвращает словарь или None в случае ошибки.
        """
        token0_address, token1_address = None, None # Инициализация для блока except
        try:
            factory_address = await self.router_contract.functions.defaultFactory().call()
            sorted_tokens = await self.router_contract.functions.sortTokens(tokenA_address, tokenB_address).call()
            token0_address = sorted_tokens[0]
            token1_address = sorted_tokens[1]
            reserves = await self.router_contract.functions.getReserves(
                token0_address,
                token1_address,
                stable,
                factory_address
            ).call()

            reserve0 = reserves[0]
            reserve1 = reserves[1]

            token0_contract = self.get_contract(token0_address)
            token1_contract = self.get_contract(token1_address)
            decimals0 = await token0_contract.functions.decimals().call()
            decimals1 = await token1_contract.functions.decimals().call()

            return {
                "reserve0": reserve0,
                "reserve1": reserve1,
                "decimals0": decimals0,
                "decimals1": decimals1,
                "token0_address": token0_address,
                "token1_address": token1_address
            }
        except Exception as e:
            tokenA_name_log = TOKEN_NAMES.get(tokenA_address, tokenA_address)
            tokenB_name_log = TOKEN_NAMES.get(tokenB_address, tokenB_address)
            if token0_address and token1_address: # Если сортировка успела произойти
                 tokenA_name_log = TOKEN_NAMES.get(token0_address, token0_address)
                 tokenB_name_log = TOKEN_NAMES.get(token1_address, token1_address)

            logger.error(f"Не удалось получить резервы для {tokenA_name_log}/{tokenB_name_log} (stable={stable}): {e}")
            if "Pair: Does not exist" in str(e) or "INSUFFICIENT_LIQUIDITY" in str(e).upper():
                 logger.warning(f"Пул для {tokenA_name_log}/{tokenB_name_log} (stable={stable}) не существует или не имеет ликвидности.")
            return None

    async def add_liquidity_eth(self, token_address, percentage, stable):
        """Добавляет ликвидность для пары ERC20 / Нативный_Токен (WXRP)."""
        token_name = TOKEN_NAMES.get(token_address, token_address)
        eth_name = TOKEN_NAMES.get(self.chain_token, self.chain_token)

        # Получаем данные пула (вывод имен токенов будет внутри get_reserves_from_pool)
        pool_data = await self.get_reserves_from_pool(token_address, self.chain_token, stable)
        if pool_data is None:
            # Ошибка уже залоггирована внутри get_reserves_from_pool
            logger.error(f"Добавление ликвидности для {token_name}/{eth_name} (stable={stable}) невозможно из-за ошибки получения резервов.")
            return None

        # Проверяем балансы
        balance_eth = await self.get_balance(self.chain_token)
        if balance_eth['amount_in_wei'] == 0:
            # Лог соответствует оригиналу
            logger.warning(f'На кошельке {self.address}, нет {eth_name}, добавить ликвидность невозможно!')
            return None

        balance_erc20 = await self.get_balance(token_address)
        if balance_erc20['amount_in_wei'] == 0:
            # Лог соответствует оригиналу
            logger.warning(f'На кошельке {self.address}, нет {token_name}, добавить ликвидность невозможно!')
            return None

        # Определяем желаемое количество ETH для добавления
        amount_wei_eth_desired = self.simplify_wei_balance(balance_eth['amount_in_wei'] * (percentage / 100))
        if amount_wei_eth_desired == 0:
             logger.warning(f"Рассчитанное количество {eth_name} для добавления равно 0 (исходный баланс: {balance_eth['amount_in_wei']}, процент: {percentage}). Пропуск.")
             return None
        amount_wei_eth_desired_human = amount_wei_eth_desired / 10 ** balance_eth['decimals']

        # Определяем порядок токенов и резервы
        if pool_data['token0_address'] == self.chain_token:
            reserve_eth = pool_data['reserve0']
            reserve_erc20 = pool_data['reserve1']
            decimals_erc20 = pool_data['decimals1']
        else:
            reserve_eth = pool_data['reserve1']
            reserve_erc20 = pool_data['reserve0']
            decimals_erc20 = pool_data['decimals0']

        # Рассчитываем необходимое количество второго токена
        if reserve_eth == 0 or reserve_erc20 == 0:
             logger.warning(f"Один из резервов в пуле {token_name}/{eth_name} (stable={stable}) равен нулю. Невозможно рассчитать пропорцию. Пропуск.")
             return None


        # 1. Максимальное количество WXRP, которое мы можем добавить (исходя из % от баланса WXRP)
        # Уберем simplify_wei_balance для начального расчета, чтобы быть точнее.
        # Упрощение применим позже к финальному выбранному значению.
        max_eth_from_balance_percentage = int(balance_eth['amount_in_wei'] * (percentage / 100))

        if max_eth_from_balance_percentage == 0:
            logger.warning(f"Рассчитанное количество {eth_name} для добавления (из % баланса) равно 0. Пропуск.")
            return None

        # 2. Сколько ERC20 потребуется для этого количества WXRP
        required_erc20_for_max_eth = int(max_eth_from_balance_percentage * reserve_erc20 / reserve_eth)

        # 3. Максимальное количество ERC20, которое мы можем добавить (исходя из % от баланса ERC20)
        # Это нужно, если мы хотим, чтобы ERC20 был "ведущим" при нехватке WXRP
        # Но для add_liquidity_ETH обычно WXRP является ведущим.
        # Поэтому, будем исходить из того, сколько WXRP мы можем себе позволить,
        # учитывая доступный баланс ERC20.

        # Сколько WXRP мы можем добавить, если у нас есть ВЕСЬ наш баланс ERC20
        # (т.е. если бы ERC20 был лимитирующим фактором)
        eth_for_full_erc20_balance = int(balance_erc20['amount_in_wei'] * reserve_eth / reserve_erc20)

        # Выбираем финальное количество WXRP для добавления:
        # Это МЕНЬШЕЕ из:
        #   а) % от нашего баланса WXRP
        #   б) количество WXRP, которое мы можем себе позволить, имея весь наш баланс ERC20
        #   в) (неявно) весь наш баланс WXRP (потому что max_eth_from_balance_percentage <= balance_eth)

        amount_wei_eth_to_add = min(max_eth_from_balance_percentage, eth_for_full_erc20_balance)

        # Теперь, когда мы определили реальное количество WXRP, которое МОЖЕМ добавить,
        # применяем simplify_wei_balance к нему.
        amount_wei_eth_desired = self.simplify_wei_balance(amount_wei_eth_to_add)

        if amount_wei_eth_desired == 0:
            logger.warning(
                f"После учета балансов и simplify, рассчитанное количество {eth_name} для добавления равно 0. Пропуск.")
            return None

        # Рассчитываем соответствующее количество ERC20 для этого amount_wei_eth_desired
        amount_wei_erc20_desired = int(amount_wei_eth_desired * reserve_erc20 / reserve_eth)

        if amount_wei_erc20_desired == 0:
            logger.error(
                f"Расчетное количество {token_name} для добавления равно 0 (из-за пропорции резервов для выбранного ETH). Добавление ликвидности невозможно.")
            return None

        amount_wei_erc20_desired_human = amount_wei_erc20_desired / 10 ** decimals_erc20

        # Логгируем попытку и рассчитанные суммы (формат как в оригинале)
        logger.info(f'Кошелек: {self.address}, попытка создания ликвидности для пары {token_name} - {eth_name}, pool: {"Stable" if stable else "Volatile"}')
        # Используем .2f для токена и без форматирования для ETH, как в оригинальном логе
        logger.info(f'{token_name}: {amount_wei_erc20_desired_human:.2f}, {eth_name}: {amount_wei_eth_desired_human}')

        # Проверяем на достаточность ERC20
        if balance_erc20['amount_in_wei'] < amount_wei_erc20_desired:
            balance_erc20["amount_in_human"]=balance_erc20['amount_in_wei']/10**balance_erc20['decimals']
            # Логи соответствуют оригиналу
            logger.warning(f'На кошельке {self.address}, не хватает {token_name}, добавить ликвидность невозможно!')
            logger.warning(f'Требуется {amount_wei_erc20_desired_human:.6f}, фактически'
                           f' {balance_erc20["amount_in_human"]:.6f}') # Используем больше знаков для точности здесь
            return None

        # Учет проскальзывания
        amount_token_min = int(amount_wei_erc20_desired * (1 - SLIPPAGE))
        amount_eth_min = int(amount_wei_eth_desired * (1 - SLIPPAGE))

        # Проверка и установка разрешения (approve)
        # Лог аппрува будет выведен из check_allowance_get_approve, если он там есть
        approved = await self.check_allowance_get_approve(token_address, ROUTER_ADDRESS, amount_wei_erc20_desired)
        await asyncio.sleep(5)

        # Подготовка и отправка транзакции
        deadline = int(time.time()) + 600
        receipt = None # Инициализация
        try:
            tx_params = await self.prepare_tx(value=amount_wei_eth_desired)
            transaction = await self.router_contract.functions.addLiquidityETH(
                token_address,
                stable,
                amount_wei_erc20_desired,
                amount_token_min,
                amount_eth_min,
                self.address,
                deadline
            ).build_transaction(tx_params)
            logger.info(f'Отправка транзакции ликвидности...')
            # Отправка транзакции (wait_tx внутри send_transaction должен логгировать успех TX)
            receipt = await self.send_transaction(transaction)
            return True

        except Exception as er:
             # Лог ошибки соответствует оригиналу
             logger.error(f'Кошелек: {self.address}, ошибка во время выполнения ликвидности для пары {token_name} - {eth_name}: {er}')
             # Дополнительная информация об ошибке (можно закомментировать, если не нужно)
             if hasattr(er, 'args') and er.args:
                  error_data = er.args[0]
                  if isinstance(error_data, dict) and 'message' in error_data: logger.error(f"Сообщение об ошибке контракта: {error_data['message']}")
                  elif isinstance(error_data, str): logger.error(f"Сообщение об ошибке (строка): {error_data}")


        # Логгируем итоговый успех операции (если receipt получен)
        if receipt:
             # Лог успеха соответствует оригиналу
             logger.success(f'Кошелек: {self.address}, ликвидность для пары {token_name} - {eth_name} успешно добавлена!')
        # Нет необходимости логгировать ошибку еще раз, она уже обработана в except

        return None # Возвращаем None независимо от результата, как в оригинале

    async def add_liquidity(self, tokenA_address, tokenB_address, percentage, stable):
        """Добавляет ликвидность для пары ERC20 / ERC20."""
        tokenA_name = TOKEN_NAMES.get(tokenA_address, tokenA_address)
        tokenB_name = TOKEN_NAMES.get(tokenB_address, tokenB_address)

        # Получаем данные пула (вывод имен токенов будет внутри get_reserves_from_pool)
        pool_data = await self.get_reserves_from_pool(tokenA_address, tokenB_address, stable)
        if pool_data is None:
            logger.error(f"Добавление ликвидности для {tokenA_name}/{tokenB_name} (stable={stable}) невозможно из-за ошибки получения резервов.")
            return None

        # Проверяем балансы
        balance_a = await self.get_balance(tokenA_address)
        if balance_a['amount_in_wei'] == 0:
            # Лог соответствует оригиналу
            logger.warning(f'На кошельке {self.address}, нет {tokenA_name}, добавить ликвидность невозможно!')
            return None

        balance_b = await self.get_balance(tokenB_address)
        if balance_b['amount_in_wei'] == 0:
             # Лог соответствует оригиналу
            logger.warning(f'На кошельке {self.address}, нет {tokenB_name}, добавить ликвидность невозможно!')
            return None

        # Определяем желаемое количество токена A
        amount_wei_a_desired = self.simplify_wei_balance(balance_a['amount_in_wei'] * (percentage / 100))
        if amount_wei_a_desired == 0:
             logger.warning(f"Рассчитанное количество {tokenA_name} для добавления равно 0. Пропуск.")
             return None
        amount_wei_a_desired_human = amount_wei_a_desired / 10 ** balance_a['decimals']

        # Определяем порядок токенов и резервы
        token0_address = pool_data['token0_address']
        reserve0 = pool_data['reserve0']
        reserve1 = pool_data['reserve1']
        decimals0 = pool_data['decimals0']
        decimals1 = pool_data['decimals1']

        if token0_address == tokenA_address: # A = token0, B = token1
            reserve_a = reserve0
            reserve_b = reserve1
            decimals_b = decimals1
        else: # A = token1, B = token0
            reserve_a = reserve1
            reserve_b = reserve0
            decimals_b = decimals0

        # Рассчитываем необходимое количество токена B
        if reserve_a == 0 or reserve_b == 0:
            logger.warning(f"Один из резервов в пуле {tokenA_name}/{tokenB_name} (stable={stable}) равен нулю. Расчет пропорции невозможен. Пропуск.")
            return None
        else:
            amount_wei_b_desired = int(amount_wei_a_desired * reserve_b / reserve_a)

        if amount_wei_b_desired == 0:
            logger.error(f"Расчетное количество {tokenB_name} для добавления равно 0. Добавление ликвидности невозможно.")
            return None

        amount_wei_b_desired_human = amount_wei_b_desired / 10 ** decimals_b

        # Логгируем попытку и рассчитанные суммы (формат как в оригинале)
        logger.info(f'Кошелек: {self.address}, попытка создания ликвидности для пары {tokenA_name} - {tokenB_name}, pool: {"Stable" if stable else "Volatile"}')
        # Используем .2f для обоих токенов, как в оригинальном логе для add_liquidity
        logger.info(f'{tokenA_name}: {amount_wei_a_desired_human}, {tokenB_name}: {amount_wei_b_desired_human}')

        # Проверяем на достаточность токена B
        if balance_b['amount_in_wei'] < amount_wei_b_desired:
            balance_b["amount_in_human"] = balance_b['amount_in_wei'] / 10 ** balance_b['decimals']
             # Логи соответствуют оригиналу
            logger.warning(f'На кошельке {self.address}, не хватает {tokenB_name}, добавить ликвидность невозможно!')
            logger.warning(f'Требуется {amount_wei_b_desired_human:.6f}, фактически {balance_b["amount_in_human"]:.6f}') # Точность для деталей
            return None

        # Учет проскальзывания
        amount_a_min = int(amount_wei_a_desired * (1 - SLIPPAGE))
        amount_b_min = int(amount_wei_b_desired * (1 - SLIPPAGE))

        # Проверка и установка разрешения (approve) для обоих токенов
        # Логи аппрува будут выведены из check_allowance_get_approve
        approved_a = await self.check_allowance_get_approve(tokenA_address, ROUTER_ADDRESS, amount_wei_a_desired)
        await asyncio.sleep(5)
        approved_b = await self.check_allowance_get_approve(tokenB_address, ROUTER_ADDRESS, amount_wei_b_desired)
        await asyncio.sleep(5)

        # Подготовка и отправка транзакции
        deadline = int(time.time()) + 600
        receipt = None # Инициализация
        try:
            tx_params = await self.prepare_tx() # ETH (value) не передается
            transaction = await self.router_contract.functions.addLiquidity(
                tokenA_address,
                tokenB_address,
                stable,
                amount_wei_a_desired,
                amount_wei_b_desired,
                amount_a_min,
                amount_b_min,
                self.address,
                deadline
            ).build_transaction(tx_params)
            logger.info(f'Отправка транзакции ликвидности...')
            # Отправка транзакции
            receipt = await self.send_transaction(transaction)
            # Логгируем итоговый успех операции (если receipt получен)
            return True
        except Exception as er:
             # Лог ошибки соответствует оригиналу
             logger.error(f'Кошелек: {self.address}, ошибка во время выполнения ликвидности для пары {tokenA_name} - {tokenB_name}: {er}')
             # Дополнительная информация об ошибке (можно закомментировать)
             if hasattr(er, 'args') and er.args:
                  error_data = er.args[0]
                  if isinstance(error_data, dict) and 'message' in error_data: logger.error(f"Сообщение об ошибке контракта: {error_data['message']}")
                  elif isinstance(error_data, str): logger.error(f"Сообщение об ошибке (строка): {error_data}")
             return False

async def pause(time_min,time_max ):
    delay = randint(time_min, time_max)
    logger.info(f'Задержка перед вызовом следующей задачи {delay} секунд')
    await asyncio.sleep(delay)

async def main(private_key, proxy=None):
    time_min = 10
    time_max = 30
    # Используем только последние символы ключа для лога
    xrpl = LiquidXRPL(private_key, proxy, RPC_URL, EXPLORER)
    custom_session = ClientSession()
    await xrpl.w3.provider.cache_async_session(custom_session)
    # # Запускаем задачи последовательно с паузами
    await xrpl.add_liquidity_eth(RISE_ADDRESS, 1, stable=False)
    await pause(time_min,time_max)
    await xrpl.add_liquidity_eth(RISE_ADDRESS, 1, stable=True)
    await pause(time_min, time_max)
    await xrpl.add_liquidity_eth(RIBBIT_ADDRESS, 0.1, stable=False)
    await pause(time_min, time_max)
    await xrpl.add_liquidity(RISE_ADDRESS, RIBBIT_ADDRESS, 1, stable=False)

    await xrpl.w3.provider.disconnect()


if __name__ == "__main__":
    # --- ВАЖНО: Замените 'YOUR_PRIVATE_KEY' на реальный приватный ключ ---
    your_private_key = ""  # <--- ВСТАВЬТЕ СЮДА СВОЙ ПРИВАТНЫЙ КЛЮЧ ДЛЯ ТЕСТА
    your_proxy = None

    asyncio.run(main(your_private_key, your_proxy))