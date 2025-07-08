import time
import requests
from datetime import datetime, timedelta

from backpack_exchange_sdk.authenticated import AuthenticationClient
from okx import Account, Trade, Funding, MarketData

from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys, load_okx_api_keys

proxy_on()  # 启用代理（如果需要）
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys()
BACKPACK_API_KEY, BACKPACK_SECRET_KEY = load_backpack_api_keys()

backpack_client = AuthenticationClient(BACKPACK_API_KEY, BACKPACK_SECRET_KEY)
okx_live_trading = "0"
okx_test_trading = "1"
okx_account_api = Account.AccountAPI(
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

# === 用户参数设置 ===
OKX_SYMBOL = "SOL-USDT-SWAP"  # OKX 的永续合约标识（示例）
BACKPACK_OKX_SYMBOL = "SOL_USDC_PERP"  # Backpack 标识
THRESHOLD_DIFF = 0.0015  # 资金费率差套利阈值（0.15%）
MAX_ORDER_USD = 1000  # 每次套利的最大 USD 头寸
MAX_LEVERAGE = 5  # 最大杠杆倍数
SETTLEMENT_WINDOW_MIN = 5  # 资金费率结算前几分钟内允许操作


# === 工具函数 ===
def get_okx_funding_rate(OKX_SYMBOL):
    url = f"https://www.okx.com/api/v5/public/funding-rate?instId={OKX_SYMBOL}"
    r = requests.get(url).json()
    rate = float(r['data'][0]['fundingRate'])
    next_funding_time = int(r['data'][0]['fundingTime']) // 1000  # 时间戳
    return rate, datetime.utcfromtimestamp(next_funding_time)


def get_backpack_price(pair):
    url = f"https://api.backpack.exchange/api/v1/market/ticker?OKX_SYMBOL={pair}"
    r = requests.get(url).json()
    return float(r['price']) if 'price' in r else None


def within_funding_window(next_funding_time, window_minutes):
    now = datetime.utcnow()
    return 0 <= (next_funding_time - now).total_seconds() <= window_minutes * 60


def execute_okx_order(OKX_SYMBOL, side, qty):
    print(f"[模拟下单] OKX {side} {qty} {OKX_SYMBOL}")
    # TODO: 接入 OKX 下单接口


def execute_backpack_order(pair, side, qty):
    print(f"[模拟下单] Backpack {side} {qty} {pair}")
    # TODO: 接入 Backpack 下单接口


# === 主套利逻辑 ===
def arbitrage_loop():
    while True:
        try:
            okx_rate, next_time = get_okx_funding_rate(OKX_SYMBOL)
            backpack_price = get_backpack_price(BACKPACK_OKX_SYMBOL)

            print(
                f"[{datetime.utcnow().isoformat()}] OKX 资金费率: {okx_rate:.4%}, Backpack 价格: {backpack_price}, 下次结算: {next_time}")

            if backpack_price is None:
                print("Backpack 获取价格失败，跳过...\n")
                time.sleep(10)
                continue

            if abs(okx_rate) >= THRESHOLD_DIFF and within_funding_window(next_time, SETTLEMENT_WINDOW_MIN):
                usd_value = min(MAX_ORDER_USD, backpack_price * 10)  # 简单头寸控制
                qty = round(usd_value / backpack_price, 2)
                direction = "LONG" if okx_rate > 0 else "SHORT"

                if direction == "LONG":
                    execute_okx_order(OKX_SYMBOL, "buy", qty)
                    execute_backpack_order(BACKPACK_OKX_SYMBOL, "sell", qty)
                else:
                    execute_okx_order(OKX_SYMBOL, "sell", qty)
                    execute_backpack_order(BACKPACK_OKX_SYMBOL, "buy", qty)

                print(">>> 完成套利下单，等待下一轮...\n")
                time.sleep(30)
            else:
                print("条件未满足，等待中...\n")
                time.sleep(20)

        except Exception as e:
            print(f"发生错误: {e}")
            time.sleep(10)


if __name__ == "__main__":
    arbitrage_loop()
