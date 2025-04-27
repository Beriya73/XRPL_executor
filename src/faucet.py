import json
import requests
from loguru import logger
from web3 import Web3,HTTPProvider
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.models.transactions import Payment, Memo
from xrpl.utils import xrp_to_drops
from xrpl.transaction import sign_and_submit, XRPLReliableSubmissionException

# Конфигурация сетей
NETWORKS = {
    "testnet": {
        "faucet": "https://faucet.altnet.rippletest.net/accounts",
        "bridge_gateway": "rNrjh1KGZk2jBR3wPfAQnoidtFFYQKbQn2",
        "bridge_network": "xrpl-evm",
        "json_rpc_url": "https://s.altnet.rippletest.net:51234/",
        "explorer":"https://testnet.xrpl.org/transactions/"
    }
}

class Xrpl_faucet():

    def __init__(self, private_key, proxy=None):
        request_kwargs = {'proxy': f'http://{proxy}'} if proxy else {}
        self.w3 = Web3(HTTPProvider(NETWORKS["testnet"]["json_rpc_url"], request_kwargs=request_kwargs))
        self.address = self.w3.to_checksum_address(self.w3.eth.account.from_key(private_key).address)

    def create_memo(self,data: str, memo_type: str) -> Memo:
        """Создает объект Memo для транзакции."""
        return Memo(
            memo_data=data.encode().hex().upper(),
            memo_type=memo_type.encode().hex().upper()
        )

    def create_payment_transaction(self,account: str, network: str, destination_address: str, amount: float) -> Payment:
        """Создает платежную транзакцию с мемами."""
        memos = [
            self.create_memo("interchain_transfer", "type"),
            self.create_memo(destination_address[2:], "destination_address"),  # Убираем '0x'
            self.create_memo(NETWORKS[network]["bridge_network"], "destination_chain"),
            self.create_memo("1700000", "gas_fee_amount")
        ]

        return Payment(
            account=account,
            amount=xrp_to_drops(amount),
            destination=NETWORKS[network]["bridge_gateway"],
            memos=memos
        )


    def generate_and_fund_wallet(self,network: str) -> dict:
        # Генерация нового кошелька
        wallet = Wallet.create()
        #logger.info(f"Generated XRPL Wallet: {wallet.classic_address}")

        # Запрос тестовых XRP через Faucet
        response = requests.post(
            NETWORKS[network]["faucet"],
            headers={"Content-Type": "application/json"},
            data=json.dumps({"destination": wallet.classic_address})
        )

        if response.status_code != 200:
            raise Exception(f"Faucet request failed: {response.text}")

        faucet_data = response.json()
        if "amount" not in faucet_data:
            raise Exception(f"Faucet did not return amount: {faucet_data}")

        # Ждем 1 секунду, чтобы средства поступили
        import time
        time.sleep(5)

        # Расчет суммы для отправки (amount - 7.09411 - 1.7)
        amount = float(faucet_data["amount"]) - 7.09411 - 1.7

        # Создание транзакции
        payment_tx = self.create_payment_transaction(wallet.classic_address, network, self.address, amount)

        # Подключение к XRPL
        client = JsonRpcClient(NETWORKS[network]["json_rpc_url"])

        try:
            # Подписание и отправка транзакции
            response = sign_and_submit(payment_tx, client, wallet, autofill=True, check_fee=True)

            if response.result.get("engine_result") != "tesSUCCESS":
                raise XRPLReliableSubmissionException(f"Transaction failed: {response.result}")

            return {
                "tx_hash": response.result["tx_json"]["hash"],
                "address": wallet.classic_address
            }
        except XRPLReliableSubmissionException as e:
            raise e
        except Exception as e:
            raise Exception(f"Unexpected error: {str(e)}")


def main(private_key,proxy=None):
    # Параметры
    network = "testnet"
    faucet = Xrpl_faucet(private_key,proxy)
    try:
        result = faucet.generate_and_fund_wallet(network)
        #logger.info("Transaction Successful!")
        logger.success(f'Кошелек: {faucet.address}, тестовые токены отосланы! Ожидается прибытие от 2мин до 2часов!')
        logger.info(f"Hash в сети XRPL: {NETWORKS[network]['explorer']}{result['tx_hash']}")
        logger.warning(f"Проверить получение в сети xrplevm: https://explorer.testnet.xrplevm.org/address/{faucet.address}")
        return True
    except Exception as e:
        logger.error(f"Error: {str(e)}")

if __name__ == "__main__":
      main(private_key='')