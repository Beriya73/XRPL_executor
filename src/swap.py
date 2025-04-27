import asyncio
import json
import time
from loguru import logger
from .client import Client
import os
import json
from random import randint
from aiohttp import ClientSession
# 1. RPC URL для сети с Chain ID 1449000
RPC_URL = "https://rpc.testnet.xrplevm.org"
CHAIN_ID = 1449000
EXPLORER = "https://explorer.testnet.xrplevm.org/tx/"


#2 Токены
WXRP_ADDRESS = "0x81Be083099c2C65b062378E74Fa8469644347BB7"
RISE_ADDRESS= "0x0c28777DEebe4589e83EF2Dc7833354e6a0aFF85"
RIBBIT_ADDRESS = "0x73ee7BC68d3f07CfcD68776512b7317FE57E1939"
# Контракты
ROUTER_ADDRESS = "0x25734cf60ca932A57A31984240DbF32215Fd96b7"
FACTORY_ADDRESS = "0x3f28f02d7534958f085D7E786B778D3C8E95c32c"

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

class SwapXRPL(Client):
    def __init__(self, private_key, proxy, rpc_url, explorer_url):
        super().__init__(private_key, proxy, rpc_url, explorer_url)
        self.router_contract = self.get_contract(ROUTER_ADDRESS, abi=router_abi)
        self.routes = None

    @classmethod
    def simplify_wei_balance(cls, wei_balance: int) -> int:
        """
        Упрощает баланс в Wei (большое целое число), сохраняя первые две
        значащие цифры и заменяя остальные нулями.

        Использует метод манипуляции со строками и выполняет отсечение (truncation),
        а не математическое округление.
        """
        # Проверка типа и значения
        if wei_balance == 0:
            return 0  # Нулевой баланс остается нулем

        # Преобразуем в строку
        s = str(int(wei_balance))
        length = len(s)

        # Если цифр 2 или меньше, возвращаем как есть
        if length <= 2:
            return wei_balance
        else:
            # Берем первые две цифры
            first_two_digits = s[:2]
            # Добавляем необходимое количество нулей
            simplified_str = first_two_digits + '0' * (length - 2)
            # Преобразуем обратно в целое число
            return int(simplified_str)

    async def get_amount_out_min(self, from_token, to_token, amount_to_wei)-> int | None:
        self.routes = [(from_token, to_token, False, FACTORY_ADDRESS)]
        try:
            amounts_out = await self.router_contract.functions.getAmountsOut(
                amount_to_wei,
                self.routes
            ).call()
            expected_output_token = amounts_out[-1]
            slippage_tolerance = 0.05  # 5%
            amount_out_min = int(expected_output_token * (1 - slippage_tolerance))
            return amount_out_min
        except Exception as e:
            logger.error(f"ОШИБКА при вызове getAmountsOut: {e}")
            return None

    async def swap_exact_eth_for_tokens(self, to_token, percentage)-> None:
        balance = await self.get_balance(WXRP_ADDRESS)
        if balance['amount_in_wei'] == 0:
            logger.warning(f'На кошельке {self.address} нет WXRP токена, свап невозможен!')
            return None
        amount_to_wei = int(balance['amount_in_wei'] * (percentage/100))
        amount_to_wei = self.simplify_wei_balance(amount_to_wei)
        human_amount =  amount_to_wei / 10 ** balance['decimals']
        from_token_name = TOKEN_NAMES.get(WXRP_ADDRESS, "Unknown Token")
        to_token_name = TOKEN_NAMES.get(to_token, "Unknown Token")
        logger.info(f"Кошелек: {self.address}, обмен {human_amount} токенов {from_token_name} -> {to_token_name}")

        amount_out_min = await self.get_amount_out_min(WXRP_ADDRESS, to_token, amount_to_wei)
        routes = [(WXRP_ADDRESS, to_token, False, FACTORY_ADDRESS)]
        recipient_address = self.address
        deadline = int(time.time()) + 60 * 15
        ref_address = "0x0000000000000000000000000000000000000000"
        try:
            approve_transaction = await self.router_contract.functions.swapExactETHForTokens(
                amount_out_min,
                routes,
                recipient_address,
                deadline,
                ref_address,
            ).build_transaction(await self.prepare_tx(value=amount_to_wei))
            logger.info(f'Отправка транзакции свапа...')
            return await self.send_transaction(approve_transaction)
        except Exception as er:
            logger.error(f'ОШИБКА при swap`e! {er}')
            return None


    async def swap_exact_tokens_for_tokens(self, from_token, to_token, percentage):
        balance = await self.get_balance(from_token)
        if balance['amount_in_wei'] == 0:
            logger.warning(f'На кошельке {self.address} нет {TOKEN_NAMES[from_token]}, свап невозможен!')
            return None
        amount_to_wei = int(balance['amount_in_wei'] * (percentage / 100))
        amount_to_wei = self.simplify_wei_balance(amount_to_wei)
        human_amount = amount_to_wei / 10 ** balance['decimals']
        from_token_name = TOKEN_NAMES.get(from_token, "Unknown Token")
        to_token_name = TOKEN_NAMES.get(to_token, "Unknown Token")
        logger.info(f"Кошелек: {self.address}, обмен {human_amount} токенов {from_token_name} -> {to_token_name}")
        await self.check_allowance_get_approve(from_token, ROUTER_ADDRESS, amount_wei=amount_to_wei)
        await asyncio.sleep(5)
        amount_out_min = await self.get_amount_out_min(from_token, to_token, amount_to_wei)
        routes = [(from_token, to_token, False, FACTORY_ADDRESS)]
        recipient_address = self.address
        deadline = int(time.time()) + 60 * 15
        ref_address = "0x0000000000000000000000000000000000000000"
        try:
            approve_transaction = await self.router_contract.functions.swapExactTokensForTokens(
                amount_to_wei,
                amount_out_min,
                routes,
                recipient_address,
                deadline,
                ref_address,
            ).build_transaction(await self.prepare_tx())
            logger.info(f'Отправка транзакции свапа...')
            return await self.send_transaction(approve_transaction)
        except Exception as er:
            logger.error(f'ОШИБКА при swap`e! {er}')
            return None


    async def swap_exact_tokens_for_eth(self, from_token, percentage):
        balance = await self.get_balance(from_token)
        if balance['amount_in_wei'] == 0:
            logger.warning(f'На кошельке {self.address} нет {TOKEN_NAMES[from_token]}, свап невозможен!')
            return None
        amount_to_wei = int(balance['amount_in_wei'] * (percentage / 100))
        amount_to_wei = self.simplify_wei_balance(amount_to_wei)
        human_amount = amount_to_wei / 10 ** balance['decimals']
        from_token_name = TOKEN_NAMES.get(from_token, "Unknown Token")
        logger.info(f"Кошелек: {self.address}, обмен {human_amount} токенов {from_token_name} -> {TOKEN_NAMES[WXRP_ADDRESS]}")
        await self.check_allowance_get_approve(from_token, ROUTER_ADDRESS, amount_wei=amount_to_wei)
        amount_out_min = await self.get_amount_out_min(from_token, WXRP_ADDRESS, amount_to_wei)
        routes = [(from_token, WXRP_ADDRESS, False, FACTORY_ADDRESS)]
        recipient_address = self.address
        deadline = int(time.time()) + 60 * 15
        ref_address = "0x0000000000000000000000000000000000000000"

        try:
            approve_transaction = await self.router_contract.functions.swapExactTokensForETH(
                amount_to_wei,
                amount_out_min,
                routes,
                recipient_address,
                deadline,
                ref_address,
            ).build_transaction(await self.prepare_tx())
            logger.info(f'Отправка транзакции свапа...')
            return await self.send_transaction(approve_transaction)
        except Exception as er:
            logger.error(f'ОШИБКА при swap`e! {er}')
            return None

def load_router_data():
    abi_file_path = os.path.join(os.path.dirname(__file__), '..', 'abi', 'router.json')
    try:
        with open(abi_file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"ОШИБКА: Файл ABI '{abi_file_path}' не найден.")
        exit()
    except json.JSONDecodeError:
        logger.error(f"ОШИБКА: Не удалось декодировать JSON из файла ABI '{abi_file_path}'.")
        exit()

async def pause(time_min,time_max ):
    delay = randint(time_min, time_max)
    logger.warning(f'Задержка перед вызовом следующей задачи {delay} секунд')
    await asyncio.sleep(delay)


async def main(private_key, proxy=None):
    time_min = 10
    time_max = 30
    xrpl = SwapXRPL(private_key, proxy, RPC_URL, EXPLORER)
    custom_session = ClientSession()
    await xrpl.w3.provider.cache_async_session(custom_session)
    # # Запускаем задачи последовательно с паузами
    await xrpl.swap_exact_eth_for_tokens(RIBBIT_ADDRESS, 5)
    await pause(time_min,time_max)
    await xrpl.swap_exact_eth_for_tokens(RISE_ADDRESS, 5)
    await pause(time_min, time_max)
    await xrpl.swap_exact_tokens_for_tokens(RIBBIT_ADDRESS,RISE_ADDRESS,  5)
    await pause(time_min,time_max)
    await xrpl.swap_exact_tokens_for_eth(RISE_ADDRESS, 5)
    await pause(time_min,time_max)
    await xrpl.swap_exact_tokens_for_tokens( RISE_ADDRESS, RIBBIT_ADDRESS, 5)
    await pause(time_min, time_max)

    await xrpl.w3.provider.disconnect()
if __name__ == "__main__":
    asyncio.run(main('', None))
