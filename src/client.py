import asyncio
from loguru import logger
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.contract import AsyncContract
from web3.exceptions import TransactionNotFound
from termcolor import cprint
from config import *
from eth_abi import decode

MULTICALL_CONTRACT = '0xcA11bde05977b3631167028862bE2a173976CA11'

MULTICALL_ABI = [{"inputs": [{"components": [{"internalType": "address", "name": "target", "type": "address"},
                                             {"internalType": "bool", "name": "allowFailure", "type": "bool"},
                                             {"internalType": "bytes", "name": "callData", "type": "bytes"}],
                              "internalType": "struct Multicall3.Call3[]", "name": "calls", "type": "tuple[]"}],
                  "name": "aggregate3", "outputs": [{"components":
                                                         [{"internalType": "bool", "name": "success", "type": "bool"},
                                                          {"internalType": "bytes", "name": "returnData",
                                                           "type": "bytes"}],
                                                     "internalType": "struct Multicall3.Result[]",
                                                     "name": "returnData", "type": "tuple[]"}],
                  "stateMutability": "payable", "type": "function"}]
ERC20_ABI = {"constant":True,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":False,"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":False,"stateMutability":"nonpayable","type":"function"},{"constant":True,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"}

import logging


class Client:
    def __init__(self, private_key, proxy, rpc_url, explorer_url):
        self.private_key = private_key
        request_kwargs = {'proxy': f'http://{proxy}'} if proxy else None
        self.rpc_url = rpc_url
        self.explorer_url=explorer_url
        self.eip_1559 = True
        self.w3 = AsyncWeb3(AsyncHTTPProvider(self.rpc_url, request_kwargs=request_kwargs))
        self.address = self.w3.to_checksum_address(self.w3.eth.account.from_key(self.private_key).address)
        self.chain_token = '0x81Be083099c2C65b062378E74Fa8469644347BB7'


    async def get_balance(self, token_address: str,check_native_token=True) -> dict:
        """
        Получает баланс кошелька.

        Возвращает:
            dict: {'amount_in_wei': amount_in_wei, "decimals": decimals, 'name': name}
        """
        NATIVE_TOKENS_PER_CHAIN = self.chain_token
        if token_address in NATIVE_TOKENS_PER_CHAIN and check_native_token:
            amount_in_wei = await self.w3.eth.get_balance(self.address)
            decimals = 18
            return {'amount_in_wei': amount_in_wei, "decimals": decimals, 'name': self.chain_token}
        else:
            token_contract = self.get_contract(
                contract_address=token_address,
                abi=ERC20_ABI)
            amount_in_wei = await token_contract.functions.balanceOf(self.address).call()
            decimals = await token_contract.functions.decimals().call()
            name = await token_contract.functions.name().call()
            return {'amount_in_wei': amount_in_wei, "decimals": decimals, 'name': name}

    def to_wei_custom(self, number: int | float, decimals: int = 18):

        unit_name = {
            6: 'mwei',
            9: 'gwei',
            18: 'ether',
        }.get(decimals)

        if not unit_name:
            raise RuntimeError(f'Can not find unit name with decimals: {decimals}')

        return self.w3.to_wei(number, unit_name)

    def from_wei_custom(self, number: int | float, decimals: int):

        unit_name = {
            6: 'mwei',
            9: 'gwei',
            18: 'ether',
        }.get(decimals)

        if not unit_name:
            raise RuntimeError(f'Can not find unit name with decimals: {decimals}')

        return self.w3.from_wei(number, unit_name)

    def get_contract(self, contract_address: str, abi: dict=ERC20_ABI) -> AsyncContract:
        return self.w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contract_address),
            abi=abi
        )

    # async def get_decimals(self, token_name: str):
    #     if token_name != self.chain_token:
    #         token_contract = self.get_contract(contract_address=TOKENS_PER_CHAIN[self.chain_name][token_name])
    #         return await token_contract.functions.decimals().call()
    #     return 18

    async def make_approve(self, token_address: str, spender_address: str, amount_in_wei: int):
        approve_transaction = await self.get_contract(contract_address=token_address, abi=ERC20_ABI).functions.approve(
            spender_address,
            amount_in_wei
        ).build_transaction(await self.prepare_tx())

        #logger.info(f'Make approve for {spender_address} in {token_address}')

        return await self.send_transaction(approve_transaction)

    async def get_priotiry_fee(self) -> int:
        fee_history = await self.w3.eth.fee_history(5, 'latest', [80.0])
        non_empty_block_priority_fees = [fee[0] for fee in fee_history["reward"] if fee[0] != 0]

        divisor_priority = max(len(non_empty_block_priority_fees), 1)
        priority_fee = int(round(sum(non_empty_block_priority_fees) / divisor_priority))

        return priority_fee

    async def prepare_tx(self, value: int | float = 0):
        transaction = {
            'chainId': await self.w3.eth.chain_id,
            'nonce': await self.w3.eth.get_transaction_count(self.address),
            'from': self.address,
            'value': value,
            'gasPrice': int((await self.w3.eth.gas_price) * 1.1)
        }

        if self.eip_1559:
            del transaction['gasPrice']

            base_fee = await self.w3.eth.gas_price
            max_priority_fee_per_gas = await self.get_priotiry_fee()

            if max_priority_fee_per_gas == 0:
                max_priority_fee_per_gas = base_fee

#            max_fee_per_gas = int(base_fee * 1.25 + max_priority_fee_per_gas)
            max_fee_per_gas = int(base_fee + max_priority_fee_per_gas)


            transaction['maxPriorityFeePerGas'] = max_priority_fee_per_gas
            transaction['maxFeePerGas'] = max_fee_per_gas
            transaction['type'] = '0x2'

        return transaction

    async def send_transaction(
            self, transaction=None, without_gas: bool = False, need_hash: bool = False, ready_tx: bytes = None
    ):
        if ready_tx:
            tx_hash_bytes = await self.w3.eth.send_raw_transaction(ready_tx)

            logger.info('Successfully sent transaction!')

            tx_hash_hex = self.w3.to_hex(tx_hash_bytes)
        else:

            if not without_gas:
                transaction['gas'] = int((await self.w3.eth.estimate_gas(transaction)) * 1.1)

            signed_raw_tx = self.w3.eth.account.sign_transaction(transaction, self.private_key).raw_transaction

            #logger.info('Successfully signed transaction!')

            tx_hash_bytes = await self.w3.eth.send_raw_transaction(signed_raw_tx)

            #logger.info('Successfully sent transaction!')

            tx_hash_hex = self.w3.to_hex(tx_hash_bytes)

        if need_hash:
            await self.wait_tx(tx_hash_hex)
            return tx_hash_hex

        return await self.wait_tx(tx_hash_hex)

    async def wait_tx(self, tx_hash):
        receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if  receipt.get("status"):
            logger.success(f'Transaction was successful: {self.explorer_url}{tx_hash}')
        else:
            logger.error(f'Transaction failed: {self.explorer_url}{tx_hash}')

    async def check_allowance(self, token_address: str, spender: str):
        """
        Проверяет количество токенов, одобренных (`allowance`) для использования контрактом.

        :return: Количество токенов в wei, которые разрешены для использования.
        :raises Exception: Если возникает ошибка во время проверки, логируется сообщение об ошибке.
        """
        try:

            # Вызов функции allowance: возвращает одобренное количество токенов
            token_contract = self.get_contract(token_address, abi=ERC20_ABI)
            amount_in_wei = await token_contract.functions.allowance(
                self.address,  # Адрес владельца токенов
                spender  # Адрес контракта, которому предоставлено разрешение
            ).call()
            # Возвращаем количество токенов в wei разрешенных для вывода spend`ером
            return amount_in_wei

        except Exception as error:
            # Логирование ошибок, если произошел сбой
            logger.error(f"Произошла ошибка во время проверки разрешения (allowance): {error}")

    async def check_allowance_get_approve(self, token_address: str, spender: str, amount: float = None,
                                          amount_wei: int = None):
        allowance_wei = await self.check_allowance(token_address, spender)
        balance_wei = await self.get_balance(token_address)
        if amount:
            amount_wei = int(amount * 10 ** balance_wei.get('decimals'))
        # Если разрешено меньше, чем текущий amount_wei, выполняем approve
        if amount_wei > allowance_wei:
            try:
                logger.warning(f"Не хватает approve. Выполняем approve на"
                       f" {amount_wei / 10 ** balance_wei.get('decimals')} токенов")
                await self.make_approve(
                    token_address,  # Адрес токена
                    spender,  # Адрес контракта spender
                    amount_wei  # Количество токенов для approve
                )

            except Exception as error:
                logger.error(f"Произошла ошибка во время выполнения approve кошелек {self.address}: {error}")
                exit(1)  # Завершаем выполнение, если approve не удался
        else:
            logger.info(f"Апрув не нужен, продолжаем...")



    async def check_balance_multicall(self, tokens_address: dict) -> list:
        """
        Проверяет балансы ERC20 токенов с использованием Multicall.
        :param tokens_address: Словарь с адресами токенов.
        :return: Список словарей с балансами токенов.
        """
        self.multicall_contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(MULTICALL_CONTRACT),
            abi=MULTICALL_ABI,
        )

        async def prepare_erc20_calls(token_address):
            """Подготавливает вызовы для ERC20 контракта."""
            token_contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )
            calls = [
                [token_contract.address, False, token_contract.encode_abi('name')],
                [token_contract.address, False, token_contract.encode_abi('decimals')],
                [token_contract.address, False, token_contract.encode_abi('balanceOf', args=[self.address])],
            ]
            return calls

        def decode_data(result_multicall):
            """Декодирует результаты вызовов Multicall."""
            balances = []
            try:
                for i in range(0, len(result_multicall), 3):
                    name_call, decimals_call, balance_call = result_multicall[i:i + 3]

                    # Извлечение имени токена
                    token_name = "Unknown"
                    if name_call[0]:  # Если вызов успешен
                        try:
                            raw_data = decode(['string'], name_call[1])[0]
                            token_name = raw_data.strip('\x00')  # Удаляем нулевые символы
                        except Exception as e:
                            logger.warning(f"Не удалось декодировать имя токена: {e}")

                    # Извлечение количества десятичных знаков
                    token_decimals = 18  # Значение по умолчанию
                    if decimals_call[0]:  # Если вызов успешен
                        try:
                            token_decimals = decode(['uint8'], decimals_call[1])[0]
                        except Exception as e:
                            logger.warning(f"Не удалось декодировать decimals для токена {token_name}: {e}")

                    # Извлечение баланса
                    token_balance = 0  # Значение по умолчанию
                    if balance_call[0]:  # Если вызов успешен
                        try:
                            token_balance = decode(['uint256'], balance_call[1])[0]
                        except Exception as e:
                            logger.warning(f"Не удалось декодировать баланс для токена {token_name}: {e}")

                    balances.append({
                        'name': token_name,
                        'amount_wei': token_balance,
                        'decimals': token_decimals,
                    })
            except Exception as e:
                logger.error(f"Ошибка при декодировании данных мультиколла: {e}")
            return balances

        # Готовим вызовы для всех токенов
        all_token_calls = []
        for token_address in tokens_address.values():
            all_token_calls.extend(await prepare_erc20_calls(token_address))

        # Выполняем aggregate3 через Multicall
        result_multicall = await self.multicall_contract.functions.aggregate3(all_token_calls).call()

        # Декодируем результаты
        return decode_data(result_multicall)


    async def get_amounts_out_multicall(self, token_in: dict, token_out: str, router_contract):
        MULTICALL_ABI = [{"inputs":[{"components":[{"internalType":"address","name":"target","type":"address"},{"internalType":"bool","name":"allowFailure","type":"bool"},{"internalType":"bytes","name":"callData","type":"bytes"}],"internalType":"struct Multicall3.Call3[]","name":"calls","type":"tuple[]"}],"name":"aggregate3","outputs":[{"components":[{"internalType":"bool","name":"success","type":"bool"},{"internalType":"bytes","name":"returnData","type":"bytes"}],"internalType":"struct Multicall3.Result[]","name":"returnData","type":"tuple[]"}],"stateMutability":"payable","type":"function"}]
        AMOUNTS_OUT_ABI = [{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]

        MULTICALL_CONTRACT = '0xcA11bde05977b3631167028862bE2a173976CA11'

        multicall_contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(MULTICALL_CONTRACT),
            abi=MULTICALL_ABI,
        )
        def prepare_erc20_calls(token):
            token_calls = []

            try:
                token_in_name = token['name']
                #token_in = TOKENS_PER_CHAIN[token_in_name]
                amount_wei = token['amount_wei']
                # print(await self.router_contract.functions.getAmountsOut(item['amount_wei'],
                #                                                          [token_in, token_out]).call())
                path = router_contract.encode_abi(
                    'getAmountsOut',
                    args=(
                        amount_wei,
                        [token_in, token_out]
                    )
                )
                return [router_contract.address, False, path]

            except Exception as e:
                logging.error(f"Ошибка при подготовке вызовов getAmountsOut: {e}")

        def decode_data_multicall(token_in_nonzero_balance, result_multicall):
            try:
                for token_in, item in zip(token_in_nonzero_balance,result_multicall):
                    if item[0]:
                        amount_out = decode(['uint256[]'], item[1])
                        token_in['amount_out_wei'] = amount_out[0][1]
                return token_in_nonzero_balance

            except Exception as e:
                logger.error(f"Ошибка при декодировании данных мультиколла: {e}")

        token_calls = []
        token_in_nonzero_balance = []

        for item in token_in:
            # Пропускаем с нулевым балансом
            if item['amount_wei'] != 0:
                token_in_nonzero_balance.append(item)
                token_calls.append(prepare_erc20_calls(item))

        result_multicall = await multicall_contract.functions.aggregate3(token_calls).call()
        result_decode = decode_data_multicall(token_in_nonzero_balance ,result_multicall)
        return result_decode