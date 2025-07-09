import time
import requests
from datetime import datetime, timedelta
from dateutil import parser

from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType, OrderSide, TimeInForce
from okx import Account, Trade, Funding, MarketData, PublicData

from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys, load_okx_api_keys

# === 初始化设置 ===
proxy_on()  # 启用代理（如果需要）
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys()
BACKPACK_API_KEY, BACKPACK_SECRET_KEY = load_backpack_api_keys()

backpack_client = AuthenticationClient(BACKPACK_API_KEY, BACKPACK_SECRET_KEY)
backpack_public = PublicClient()
okx_live_trading = "0"
okx_account_api = Account.AccountAPI(
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_funding_api = Funding.FundingAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_public_api = PublicData.PublicAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

# === 套利参数设置 ===
# 合约标的映射：OKX 合约 -> Backpack 合约

SYMBOL_MAP = {
    "BTC-USDT-SWAP": "BTC_USDC_PERP",
    "ETH-USDT-SWAP": "ETH_USDC_PERP",
    "SOL-USDT-SWAP": "SOL_USDC_PERP",
    "SUI-USDT-SWAP": "SUI_USDC_PERP",
    "XRP-USDT-SWAP": "XRP_USDC_PERP",
    "DOGE-USDT-SWAP": "DOGE_USDC_PERP",
    "KAITO-USDT-SWAP": "KAITO_USDC_PERP",
}
OKX_SYMBOL = "SOL-USDT-SWAP"  # OKX 的永续合约标识（示例）
BACKPACK_SYMBOL = "SOL_USDC_PERP"  # Backpack 标识
THRESHOLD_DIFF_Y = 0.1  # 资金费率差套利阈值年化（10%）
MAX_ORDER_USD = 1000  # 每次套利的最大 USD 头寸
MAX_LEVERAGE = 5  # 最大杠杆倍数
SETTLEMENT_WINDOW_MIN = 15  # 资金费率结算前几分钟内允许操作


# === 工具函数 ===
# 获取 OKX 标的资金费率,结算时间,下次结算时间
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
    print(f"okx 资金费率: {rate:.4%}, 结算时间: {funding_time_read}, 下次结算时间: {next_funding_time_read}")

    return rate, funding_time, next_funding_time


# 获取 Backpack 标的资金费率
def get_backpack_funding_rate(public, symbol):
    # backpack以区间形式返回最近的资金费率，limit设置为1，代表最新的一条
    resp = public.get_funding_interval_rates(symbol=symbol, limit=1)
    if not resp:
        raise Exception("无法获取 Backpack 资金费率信息")

    data = resp[0] if isinstance(resp, list) else resp
    rate = float(str(data.get("fundingRate")))
    interval_end_timestamp = parser.parse(data["intervalEndTimestamp"])  # backpack返回的是上次结算后的本地时间2025-07-08T16:00:00
    funding_time = interval_end_timestamp + timedelta(hours=8)  # Backpack 的资金费率是每8小时结算一次

    print(f"Backpack 资金费率: {rate:.4%}, 结算时间: {funding_time}")
    funding_time_unix = int(funding_time.timestamp() * 1000)  # 转换为毫秒时间戳

    return rate, funding_time_unix


# 判断当前时间是否在交易窗口内
def within_funding_window(next_funding_time, window_minutes):
    now = datetime.now()
    return 0 <= (next_funding_time - now).total_seconds() <= window_minutes * 60


# 计算两个交易所的资金费率差，并计算年化收益并给标的排序def calculate_funding_rate_diff():
def calculate_funding_rate_diff():
    results = []
    for okx_symbol, backpack_symbol in SYMBOL_MAP.items():
        try:
            okx_rate, okx_funding_time, _ = get_okx_funding_rate(okx_public_api, okx_symbol)
            backpack_rate, backpack_funding_time = get_backpack_funding_rate(backpack_public, backpack_symbol)
            diff = okx_rate - backpack_rate
            # 资金费率通常8小时结算一次，年化=单次费率*3*365
            annualized = abs(diff) * 3 * 365
            # 计算交易方向
            if okx_rate >= 0 > backpack_rate:
                okx_action, backpack_action = ("short", "long")
            elif okx_rate < 0 <= backpack_rate:
                okx_action, backpack_action = ("long", "short")
            elif okx_rate > backpack_rate >= 0:
                okx_action, backpack_action = ("short", "long")
            elif okx_rate < backpack_rate <= 0:
                okx_action, backpack_action = ("long", "short")
            elif backpack_rate > okx_rate >= 0:
                okx_action, backpack_action = ("long", "short")
            elif backpack_rate < okx_rate <= 0:
                okx_action, backpack_action = ("short", "long")
            else:
                okx_action, backpack_action = ("hold", "hold")
            # 若资金费率结算时间不一致，无套利空间
            if int(okx_funding_time) != int(backpack_funding_time):
                print(f"资金费率结算时间不一致: OKX={okx_funding_time}, Backpack={backpack_funding_time}")
                okx_action, backpack_action = ("hold", "hold")

            results.append({
                "okx_symbol": okx_symbol,
                "backpack_symbol": backpack_symbol,
                "okx_rate": okx_rate,
                "backpack_rate": backpack_rate,
                "diff": diff,
                "annualized": annualized,
                "next_funding_time": okx_funding_time,
                "okx_action": okx_action,
                "backpack_action": backpack_action
            })
        except Exception as e:
            print(f"获取{okx_symbol}资金费率失败: {e}")
    # 按年化收益降序排序
    results.sort(key=lambda x: x["annualized"], reverse=True)
    for r in results:
        print(
            f"{r['okx_symbol']} <-> {r['backpack_symbol']}: 差值={r['diff']:.4%}, 年化={r['annualized']:.4%}, "
            f"OKX={r['okx_rate']:.4%}, Backpack={r['backpack_rate']:.4%}"f", OKX操作={r['okx_action']}, "
            f"Backpack操作={r['backpack_action']}, 下次结算时间={r['next_funding_time']}")
    return results


# 在 OKX 上执行合约下单
def execute_okx_order_swap(symbol, side, qty, price, order_type="market"):
    if side not in ["long", "short"]:
        raise ValueError("OKX 下单方向必须是 'long' 或 'short'")

    # 设置账户模式为合约
    position_mode_result = okx_account_api.set_position_mode(
        posMode="long_short_mode",  # 开平仓模式
    )
    # 设置合约交易参数
    leverage_result = okx_account_api.set_leverage(
        instId=symbol,  # 交易对
        mgnMode="isolated",  # 逐仓模式
        lever=str(MAX_LEVERAGE),  # 杠杆倍数
        posSide=side
    )
    print(f"[OKX] 设置账户模式和杠杆: {position_mode_result}, {leverage_result}")
    if position_mode_result.get("code") != "0" or leverage_result.get("code") != "0":
        raise Exception("OKX 设置账户模式或杠杆失败")
    # 执行下单
    order_result = okx_trade_api.place_order(
        instId=symbol,  # 交易对
        tdMode="isolated",  # 逐仓模式
        side="sell" if side == "short" else "buy",  # 做空或做多
        ordType=order_type,  # 市价单
        sz=str(qty),  # 下单数量（合约张数）
        px=price
    )
    print(f"[OKX] 下单结果: {order_result}")
    if order_result.get("code") != "0":
        raise Exception(f"OKX 下单失败: {order_result.get('msg')}")


# 在backpack 上执行合约下单
def execute_backpack_order(symbol, side, qty, price, order_type=OrderType.MARKET):
    if side not in ["long", "short"]:
        raise ValueError("Backpack 下单方向必须是 'long' 或 'short'")
    # 设置合约交易参数
    backpack_client.update_account(
        leverageLimit=str(MAX_LEVERAGE)
    )

    # 执行下单
    order_result = backpack_client.execute_order(
        orderType=order_type,
        side=OrderSide.BID if side == "long" else OrderSide.ASK,
        symbol=symbol,
        quantity=str(qty),  # 数量单位为合约张数
        timeInForce=TimeInForce.GTC,  # Good Till Cancelled
        postOnly=True,  # 确保是挂单而非吃单,限价单才生效
        price=price
    )
    print(f"[Backpack] 下单结果: {order_result}")
    if not order_result or "error" in order_result:
        raise Exception(f"Backpack 下单失败: {order_result.get('error', '未知错误')}")
    return order_result


# === 主套利逻辑 ===
def arbitrage_loop():
    is_open = False
    open_info = {}  # 保存开仓的信息（等待应应收益和平仓）

    while True:
        try:
            print("\n==== 开始断判深度契约资金费率契约奖励 ====")
            now = datetime.now()

            if not is_open:
                results = calculate_funding_rate_diff()
                # 筛选最大差值并且要求资金费率差大于阈值，无 hold，并在窗口期内
                for r in results:
                    if (
                            r["annualized"] >= THRESHOLD_DIFF_Y
                            and r["okx_action"] != "hold"
                            and r["backpack_action"] != "hold"
                            and within_funding_window(datetime.fromtimestamp(r["next_funding_time"] / 1000),
                                                      SETTLEMENT_WINDOW_MIN)
                    ):
                        # 执行开仓
                        print("\n>> 开始执行开仓...")
                        qty = round(MAX_ORDER_USD / 5, 2)  # 例如假设单位为 1U
                        execute_okx_order_swap(r["okx_symbol"], r["okx_action"], qty)
                        execute_backpack_order(r["backpack_symbol"], r["backpack_action"], qty)

                        open_info = {
                            "okx_symbol": r["okx_symbol"],
                            "backpack_symbol": r["backpack_symbol"],
                            "okx_action": r["okx_action"],
                            "backpack_action": r["backpack_action"],
                            "entry_time": now,
                            "close_time": r["next_funding_time"]
                        }
                        is_open = True
                        break  # 只执行一小组
                else:
                    print("暂无合适契约可执行奖励")

            else:
                # 已开仓，进行监控
                now_ts = int(datetime.now().timestamp() * 1000)

                if now_ts >= open_info["close_time"]:
                    print("\n>> 到达应收益时点，开始平仓")
                    # TODO: 平仓操作
                    # TODO: 计算收益
                    print("[OKX]平仓", open_info["okx_symbol"])
                    print("[Backpack]平仓", open_info["backpack_symbol"])
                    print(">> 本转奖励已经完成\n")

                    is_open = False
                    open_info = {}
                else:
                    print(">> 未到结算时间，预估收益情况:")
                    # TODO: 计算预估收益（新的资金费率 × 仓位）
                    print("[暂无实际计算]")

            time.sleep(300)  # 每5分钟重试

        except Exception as e:
            print("[异常]", e)
            time.sleep(60)


if __name__ == "__main__":
    arbitrage_loop()
