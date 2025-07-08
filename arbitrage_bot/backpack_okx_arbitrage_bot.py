import time
import requests
from datetime import datetime, timedelta

from backpack_exchange_sdk.authenticated import AuthenticationClient
from okx import Account, Trade, Funding, MarketData, PublicData

from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys, load_okx_api_keys

# === 初始化设置 ===
proxy_on()  # 启用代理（如果需要）
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys()
BACKPACK_API_KEY, BACKPACK_SECRET_KEY = load_backpack_api_keys()

backpack_client = AuthenticationClient(BACKPACK_API_KEY, BACKPACK_SECRET_KEY)
okx_live_trading = "0"
okx_account_api = Account.AccountAPI(
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_funding_api = Funding.FundingAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_public_api = PublicData.PublicAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

# === 套利参数设置 ===
OKX_SYMBOL = "SOL-USDT-SWAP"  # OKX 的永续合约标识（示例）
BACKPACK_SYMBOL = "SOL_USDC_PERP"  # Backpack 标识
THRESHOLD_DIFF = 0.0015  # 资金费率差套利阈值（0.15%）
MAX_ORDER_USD = 1000  # 每次套利的最大 USD 头寸
MAX_LEVERAGE = 5  # 最大杠杆倍数
SETTLEMENT_WINDOW_MIN = 5  # 资金费率结算前几分钟内允许操作


# === 工具函数 ===
# 获取 OKX 资金费率,结算时间,下次结算时间
def get_okx_funding_rate(public_api, symbol):
    funding_info = public_api.get_funding_rate(symbol)

    if not funding_info or 'data' not in funding_info or not funding_info['data']:
        raise Exception("无法获取 OKX 资金费率信息")

    latest_funding = funding_info['data'][0]
    rate = float(latest_funding['fundingRate'])
    funding_time = latest_funding['fundingTime']  # unix毫秒格式，当前费率计算时间
    next_funding_time = latest_funding['nextFundingTime']

    # 转换为本地时间进行可读性输出
    funding_time_read = datetime.fromtimestamp(int(funding_time) / 1000)
    next_funding_time_read = datetime.fromtimestamp(int(next_funding_time) / 1000)
    print(f"资金费率: {rate:.4%}, 结算时间: {funding_time_read}, 下次结算时间: {next_funding_time_read}")

    return rate, funding_time, next_funding_time


def get_backpack_funding_rate(client, symbol):

    # backpack以区间形式返回最近的资金费率，limit设置为1，代表最新的一条
    resp = client.get_funding_interval_rates(symbol=symbol, limit=1)
    if not resp:
        raise Exception("无法获取 Backpack 资金费率信息")
    print(f"Backpack 资金费率响应: {resp}")
    rate = float(resp["fundingRate"])
    intervalEndTimestamp = resp["intervalEndTimestamp"]  # backpack返回的是上次结算后的本地时间2025-07-08T16:00:00
    # 可选：打印信息
    print(f"Backpack 资金费率: {rate:.4%}, 结算时间: {intervalEndTimestamp}")
    return rate, intervalEndTimestamp


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
            backpack_price = get_backpack_funding_rate(BACKPACK_SYMBOL)

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
                    execute_backpack_order(BACKPACK_SYMBOL, "sell", qty)
                else:
                    execute_okx_order(OKX_SYMBOL, "sell", qty)
                    execute_backpack_order(BACKPACK_SYMBOL, "buy", qty)

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
