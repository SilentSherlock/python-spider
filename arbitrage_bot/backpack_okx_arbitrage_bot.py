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
okx_market_api = MarketData.MarketAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

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


# 计算两个交易所的资金费率差，并计算年化收益并给标的排序
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


# 在 OKX 上执行合约下单，待优化，设置止损
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
    return order_result


# 在 OKX 上根据订单ID检查挂单是否成交
def check_okx_order_filled(symbol, order_id, max_attempts=30, interval=1):
    """
    检查OKX订单是否成交，每1秒检查一次，最多检测max_attempts次。
    :param symbol: 合约标的
    :param order_id: 订单ID
    :param max_attempts: 最大检测次数
    :param interval: 检查间隔秒数
    :return: True-已成交，False-未成交已取消
    """
    for attempt in range(max_attempts):
        order_info = okx_trade_api.get_order(instId=symbol, ordId=order_id)
        if not order_info or order_info.get("code") != "0":
            print(f"查询OKX订单失败: {order_info.get('msg', '未知错误')}")
            break
        data = order_info["data"][0]
        state = data.get("state")
        if state == "filled":
            print(f"订单已成交: {order_id}")
            return True
        elif state in ("canceled", "cancelled"):
            print(f"订单已取消: {order_id}")
            return False
        time.sleep(interval)
    # 超时未成交，取消订单
    print(f"订单{order_id}未成交，准备取消")
    cancel_result = okx_trade_api.cancel_order(instId=symbol, ordId=order_id)
    print(f"取消订单结果: {cancel_result}")
    return False


# 在 OKX 上根据订单ID进行合约平仓
def close_okx_position_by_order_id(symbol, order_id):
    """
    根据订单ID平仓：查询订单，获取参数，反向下单
    :param symbol: 合约标的
    :param order_id: 需平仓的订单ID
    """
    # 查询订单详情
    order_info = okx_trade_api.get_order(instId=symbol, ordId=order_id)
    if not order_info or order_info.get("code") != "0":
        raise Exception(f"查询OKX订单失败: {order_info.get('msg', '未知错误')}")
    data = order_info["data"][0]
    pos_side = data.get("posSide", "net")
    side = data["side"]
    qty = data["sz"]
    price = data.get("px", None)
    # ord_type = data.get("ordType", "market")
    ord_type = "market"  # 默认使用市价单平仓
    # 反向方向
    close_side = "buy" if side == "sell" else "sell"
    print(f"[OKX] 准备平仓: {symbol}, 方向: {close_side}, 数量: {qty}, 价格: {price}, 类型: {ord_type}")
    # 平仓下单
    order_result = okx_trade_api.place_order(
        instId=symbol,
        tdMode="isolated",
        side=close_side,
        ordType=ord_type,
        sz=qty,
        px=price,
        posSide=pos_side,
        reduceOnly=True
    )
    print(f"[OKX] 平仓结果: {order_result}")
    if order_result.get("code") != "0":
        raise Exception(f"OKX 平仓失败: {order_result.get('msg', '未知错误')}")
    return order_result


# 在backpack 上执行合约下单，待优化，设置止损
def execute_backpack_order(symbol, side, qty, price, order_type=OrderType.MARKET):
    if side not in ["long", "short"]:
        raise ValueError("Backpack 下单方向必须是 'long' 或 'short'")
    # 设置合约交易参数
    backpack_client.update_account(
        leverageLimit=str(MAX_LEVERAGE)  # 杠杆倍数
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


# 在backpack 上根据订单ID检查挂单是否成交
def check_backpack_order_filled(symbol, order_id, max_attempts=30, interval=1):
    """
    检查Backpack订单是否成交，每1秒检查一次，最多检测max_attempts次。
    :param symbol: 合约标的
    :param order_id: 订单ID
    :param max_attempts: 最大检测次数
    :param interval: 检查间隔秒数
    :return: True-已成交，False-未成交已取消
    """
    for attempt in range(max_attempts):
        fill_order = backpack_client.get_fill_history(symbol=symbol, orderId=order_id)
        if not fill_order or "error" in fill_order:
            print(f"查询Backpack订单失败: {fill_order.get('error', '未知错误') if fill_order else '无返回'}")
            break
        if fill_order and len(fill_order) > 0:
            print(f"订单已成交: {order_id}")
            return True
        time.sleep(interval)
    print(f"订单{order_id}未成交，准备取消")
    backpack_client.cancel_open_order(symbol=symbol, orderId=order_id)
    return False


# 在backpack 上进行合约平仓（通过订单ID反向下单）,开仓后才可平仓，合约挂单未成交不算平仓
def close_backpack_position_by_order_id(symbol, order_id):
    """
    根据订单ID平仓：查询订单，获取参数，反向下单
    :param symbol:
    :param order_id: 需平仓的订单ID
    """
    # 查询订单详情
    order_info = backpack_client.get_users_open_orders(symbol=symbol, orderId=order_id)
    if not order_info or "error" in order_info:
        raise Exception(f"查询订单失败: {order_info.get('error', '未知错误')}")
    print(f"[Backpack] 查询到订单信息: {order_info}")
    symbol = order_info["symbol"]
    side = order_info["side"]
    qty = order_info["quantity"]
    price = order_info["price"]
    # order_type = order_info.get("orderType", OrderType.MARKET)
    order_type = OrderType.MARKET  # 默认使用市价单平仓
    # 反向方向
    close_side = "short" if side == "Bid" else "long"
    # 平仓下单
    print(f"[Backpack] 准备平仓: {symbol}, 方向: {close_side}, 数量: {qty}, 价格: {price}, 类型: {order_type}")
    order_result = backpack_client.execute_order(
        orderType=order_type,
        side=OrderSide.ASK if close_side == "short" else OrderSide.BID,
        symbol=symbol,
        quantity=str(qty),
        timeInForce=TimeInForce.GTC,
        postOnly=True,
        price=price,
        reduceOnly=True  # 确保是平仓操作
    )
    print(f"[Backpack] 平仓结果: {order_result}")
    if not order_result or "error" in order_result:
        raise Exception(f"Backpack 平仓失败: {order_result.get('error', '未知错误')}")
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
                        # 执行开仓前准备工作
                        print("\n>> 开始执行开仓前准备...")
                        # 获取当前标的最新价格
                        okx_ticker = okx_market_api.get_ticker(instId=r["okx_symbol"])
                        okx_price = float(
                            okx_ticker["data"][0]["last"]) if okx_ticker and "data" in okx_ticker else None
                        backpack_ticker = backpack_public.get_ticker(r["backpack_symbol"])
                        backpack_price = float(backpack_ticker[
                                                   "lastPrice"]) if backpack_ticker and "lastPrice" in backpack_ticker else None
                        print(f"OKX最新价: {okx_price}, Backpack最新价: {backpack_price}")
                        price = (okx_price + backpack_price) / 2 if okx_price and backpack_price else None
                        qty = int((MAX_ORDER_USD * MAX_LEVERAGE) / ((okx_price + backpack_price) / 2))
                        try:
                            okx_result = execute_okx_order_swap(r["okx_symbol"], r["okx_action"], qty, price,
                                                                order_type="limit")
                            # 检查OKX订单是否成交
                            check_okx_order_filled(r["okx_symbol"], okx_result["data"][0].get("ordId"))
                            backpack_result = execute_backpack_order(r["backpack_symbol"], r["backpack_action"], qty,
                                                                     price, order_type=OrderType.LIMIT)
                        except Exception as e:
                            print(f"[异常] 执行开仓失败: {e}")
                            # todo okx开仓成功，backpack开仓失败，取消订单或平仓处理
                            continue
                        print(f"[OKX]开仓: {r['okx_symbol']}, 方向: {r['okx_action']}, 数量: {qty}, 价格: {price}")

                        open_info = {
                            "okx_symbol": r["okx_symbol"],
                            "backpack_symbol": r["backpack_symbol"],
                            "okx_action": r["okx_action"],
                            "backpack_action": r["backpack_action"],
                            "entry_time": now,
                            "close_time": r["next_funding_time"],
                            "okx_order_id": okx_result["data"][0].get("ordId"),
                            "backpack_order_id": backpack_result.get("id"),
                        }
                        is_open = True
                        break  # 只执行一组
                else:
                    print("暂无合适资金费率套利")

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
            # todo 订单是否成功挂单，进行取消或平仓处理
            time.sleep(60)


if __name__ == "__main__":
    arbitrage_loop()
