import time
import random
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient


# 从本地文件读取 API Key 和 Secret
def load_api_keys(path="C:\\Users\\15361\\OneDrive\\文档\\finance\\TradeCat.txt"):
    with open(path, "r") as f:
        lines = f.read().splitlines()
    api_key = lines[0].strip()
    secret_key = lines[1].strip()
    return api_key, secret_key


# 初始化客户端
api_key, secret_key = load_api_keys()
client = AuthenticationClient(public_key=api_key, secret_key=secret_key)
public = PublicClient()

SYMBOL = "SOL_USDC"
BASE_AMOUNT_USD = 10  # 每次交易 10 美元等值的 SOL


def get_last_price():
    ticker = public.get_ticker(SYMBOL)
    return float(ticker["lastPrice"])


def market_trade_cycle():
    price = get_last_price()
    qty = round(BASE_AMOUNT_USD / price, 5)

    print(f"尝试以市价买入 {qty} SOL")
    buy_result = client.create_order(symbol=SYMBOL, side="BUY", type="MARKET", size=str(qty))
    print(f"买入结果: {buy_result}")

    time.sleep(random.uniform(1, 3))  # 稍作等待，模拟真实交易行为

    print(f"尝试以市价卖出 {qty} SOL")
    sell_result = client.create_order(symbol=SYMBOL, side="SELL", type="MARKET", size=str(qty))
    print(f"卖出结果: {sell_result}")


if __name__ == "__main__":
    while True:
        try:
            market_trade_cycle()
            time.sleep(random.uniform(10, 20))  # 控制频率，防止风控
        except Exception as e:
            print(f"发生错误：{e}")
            time.sleep(5)
