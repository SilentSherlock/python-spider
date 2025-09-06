import time
from datetime import datetime, timedelta

import requests
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from dateutil import parser
from enums.RequestEnums import OrderType, OrderSide, TimeInForce
from okx import Account, Trade, Funding, MarketData, PublicData

from backpack_exchange.trade_prepare import (proxy_on, load_okx_api_keys_trade_cat_okx,
                                             load_backpack_api_keys_trade_cat_funding)
from utils.logging_setup import setup_logger

# === 初始化设置 ===
proxy_on()  # 启用代理（如果需要）
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys_trade_cat_okx()
BACKPACK_API_KEY, BACKPACK_SECRET_KEY = load_backpack_api_keys_trade_cat_funding()

backpack_funding_client = AuthenticationClient(BACKPACK_API_KEY, BACKPACK_SECRET_KEY)
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
    "BNB-USDT-SWAP": "BNB_USDC_PERP",
    "FARTCOIN-USDT-SWAP": "FARTCOIN_USDC_PERP",
    "AAVE-USDT-SWAP": "AAVE_USDC_PERP",
    "HYPE-USDT-SWAP": "HYPE_USDC_PERP",
}

SYMBOL_OKX_INSTRUMENT_MAP = {'BTC-USDT-SWAP': {'lotsz': '0.01', 'minsz': '0.01', 'ctVal': '0.01'},
                             'ETH-USDT-SWAP': {'lotsz': '0.01', 'minsz': '0.01', 'ctVal': '0.1'},
                             'SOL-USDT-SWAP': {'lotsz': '0.01', 'minsz': '0.01', 'ctVal': '1'},
                             'SUI-USDT-SWAP': {'lotsz': '1', 'minsz': '1', 'ctVal': '1'},
                             'XRP-USDT-SWAP': {'lotsz': '0.01', 'minsz': '0.01', 'ctVal': '100'},
                             'DOGE-USDT-SWAP': {'lotsz': '0.01', 'minsz': '0.01', 'ctVal': '1000'},
                             'KAITO-USDT-SWAP': {'lotsz': '1', 'minsz': '1', 'ctVal': '1'},
                             'BNB-USDT-SWAP': {'lotsz': '1', 'minsz': '1', 'ctVal': '0.01'},
                             'AAVE-USDT-SWAP': {'lotsz': '0.1', 'minsz': '0.1', 'ctVal': '0.1'}}
OKX_SYMBOL = "SOL-USDT-SWAP"  # OKX 的永续合约标识（示例）
BACKPACK_SYMBOL = "SOL_USDC_PERP"  # Backpack 标识
THRESHOLD_DIFF_Y = 0.07  # 资金费率差套利阈值年化（10%）
MAX_ORDER_USD = 1000  # 每次套利的最大 USD 头寸
MAX_LEVERAGE = 10  # 最大杠杆倍数
SETTLEMENT_WINDOW_MIN = 30  # 资金费率结算前几分钟内允许操作
logger = setup_logger(__name__)


# === 工具函数 ===
# 计算合约张数
def calc_qty(symbol_price, margin_usdt, leverage, ct_val):
    """
    计算公式
    合约张数 = (保证金 * 杠杆数) / 标的价格 / 合约面值
    :param symbol_price: 标的价格
    :param margin_usdt: 保证金
    :param leverage: 杠杆数
    :param ct_val:合约面值
    :return: 合约张数
    """
    position_usdt = margin_usdt * leverage
    token_amount = position_usdt / symbol_price
    return float(token_amount / ct_val)  #


# 计算合约数目，币本位
def calc_qty_backpack(symbol_price, margin_usdt, leverage):
    """
    计算公式
    合约张数 = (保证金 * 杠杆数) / 标的价格
    :param symbol_price: 标的价格
    :param margin_usdt: 保证金
    :param leverage: 杠杆数
    :return: 合约张数
    """
    position_usdt = margin_usdt * leverage
    token_amount = position_usdt / symbol_price
    return float(token_amount)  # 返回张数


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
    logger.info(
        f"okx symbol {symbol} 资金费率: {rate:.4%}, 结算时间: {funding_time_read}, 下次结算时间: {next_funding_time_read}")

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

    logger.info(f"Backpack symbol {symbol} 资金费率: {rate:.4%}, 结算时间: {funding_time}")
    funding_time_unix = int(funding_time.timestamp() * 1000)  # 转换为毫秒时间戳

    return rate, funding_time_unix


# 判断当前时间是否在交易窗口内
def within_funding_window(next_funding_time, window_minutes):
    now = datetime.now()
    result = 0 <= int((next_funding_time - now).total_seconds()) <= window_minutes * 60
    logger.info(f"当前时间在交易窗口内: {result}, 下次结算时间: {next_funding_time}, 当前时间: {now}")
    return result


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
                logger.info(f"资金费率结算时间不一致: OKX={okx_funding_time}, Backpack={backpack_funding_time}")
                okx_action, backpack_action = ("hold", "hold")

            # 没有合约参数信息，无套利空间 待定可修改，主要是hype和fartcoin的合约参数不确定
            if okx_symbol not in SYMBOL_OKX_INSTRUMENT_MAP.keys():
                logger.info(f"合约参数信息缺失: {okx_symbol} 无法进行套利")
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
            logger.info(f"获取{okx_symbol}资金费率失败: {e}")
    # 按年化收益降序排序
    results.sort(key=lambda x: x["annualized"], reverse=True)
    for r in results:
        logger.info(
            f"{r['okx_symbol']} <-> {r['backpack_symbol']}: 差值={r['diff']:.4%}, 年化={r['annualized']:.4%}, "
            f"OKX={r['okx_rate']:.4%}, Backpack={r['backpack_rate']:.4%}"f", OKX操作={r['okx_action']}, "
            f"Backpack操作={r['backpack_action']}, 下次结算时间={r['next_funding_time']}")
    return results


# 在 OKX 上执行合约下单，待优化，设置止损
def execute_okx_order_swap(symbol, side, qty, price, order_type="market",
                           account_api=okx_account_api, trade_api=okx_trade_api, okx_leverage=MAX_LEVERAGE):
    if side not in ["long", "short"]:
        raise ValueError("OKX 下单方向必须是 'long' 或 'short'")

    # 设置账户模式为合约
    position_mode_result = account_api.set_position_mode(
        posMode="long_short_mode",  # 开平仓模式
    )
    # 设置合约交易参数
    leverage_result = account_api.set_leverage(
        instId=symbol,  # 交易对
        mgnMode="isolated",  # 逐仓模式
        lever=str(okx_leverage),  # 杠杆倍数
        posSide=side
    )
    logger.info(f"[OKX] 设置账户模式和杠杆: {position_mode_result}, {leverage_result}")
    if position_mode_result.get("code") != "0" or leverage_result.get("code") != "0":
        logger.info(f"OKX 设置账户模式或杠杆失败: {position_mode_result}, {leverage_result}, 已设置过，直接开仓")
        # raise Exception("OKX 设置账户模式或杠杆失败")
    # 执行下单
    order_result = trade_api.place_order(
        instId=symbol,  # 交易对
        tdMode="isolated",  # 逐仓模式
        side="sell" if side == "short" else "buy",  # 做空或做多
        ordType=order_type,  # 市价单
        sz=str(qty),  # 下单数量（合约张数）
        px=price,
        posSide=side,  # 持仓方向
    )
    logger.info(f"[OKX] 下单结果: {order_result}")
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
            logger.info(f"查询OKX订单失败: {order_info.get('msg', '未知错误')}")
            break
        data = order_info["data"][0]
        state = data.get("state")
        if state == "filled":
            logger.info(f"订单已成交: {order_id}")
            return True
        elif state in ("canceled", "cancelled"):
            logger.info(f"订单已取消: {order_id}")
            return False
        time.sleep(interval)
    # 超时未成交，取消订单
    logger.info(f"订单{order_id}未成交，准备取消")
    cancel_result = okx_trade_api.cancel_order(instId=symbol, ordId=order_id)
    logger.info(f"取消订单结果: {cancel_result}")
    return False


# 在 OKX 上根据订单ID进行合约平仓
def close_okx_position_by_order_id(symbol, order_id, okx_qty, trade_api=okx_trade_api):
    """
    根据订单ID平仓：查询订单，获取参数，反向下单
    :param okx_qty: 平仓数量，如果传入None，则使用订单中的数量
    :param symbol: 合约标的
    :param order_id: 需平仓的订单ID
    """
    # 查询订单详情
    order_info = trade_api.get_order(instId=symbol, ordId=order_id)
    if not order_info or order_info.get("code") != "0":
        raise Exception(f"查询OKX订单失败: {order_info.get('msg', '未知错误')}")
    data = order_info["data"][0]
    pos_side = data.get("posSide", "net")
    side = data["side"]
    qty = data["sz"] if okx_qty is None else okx_qty  # 如果传入了数量，则使用传入的数量，否则使用订单中的数量
    price = data.get("px", None)
    # ord_type = data.get("ordType", "market")
    ord_type = "market"  # 默认使用市价单平仓
    # 反向方向
    close_side = "buy" if side == "sell" else "sell"
    logger.info(f"[OKX] 准备平仓: {symbol}, 方向: {close_side}, 数量: {qty}, 价格: {price}, 类型: {ord_type}")
    # 平仓下单
    order_result = trade_api.place_order(
        instId=symbol,
        tdMode="isolated",
        side=close_side,
        ordType=ord_type,
        sz=qty,
        px=price,
        posSide=pos_side,
        reduceOnly=True
    )
    logger.info(f"[OKX] 平仓结果: {order_result}")
    if order_result.get("code") != "0":
        raise Exception(f"OKX 平仓失败: {order_result.get('msg', '未知错误')}")
    return order_result


# 在backpack 上执行合约下单，待优化，设置止损
def execute_backpack_order(symbol, side, qty, price, order_type=OrderType.MARKET, leverage=MAX_LEVERAGE, backpack_client=backpack_funding_client):
    if side not in ["long", "short"]:
        raise ValueError("Backpack 下单方向必须是 'long' 或 'short'")
    # 设置合约交易参数
    backpack_client.update_account(
        leverageLimit=str(leverage)  # 杠杆倍数
    )

    # 执行下单

    try:

        order_result = backpack_client.execute_order(
            orderType=order_type,
            side=OrderSide.BID if side == "long" else OrderSide.ASK,
            symbol=symbol,
            quantity=str(qty),  # 数量单位为合约张数
            timeInForce=TimeInForce.GTC,  # Good Till Cancelled
            postOnly=True,  # 确保是挂单而非吃单,限价单才生效
            price=price
        )
    except requests.exceptions.RequestException as e:
        logger.info(f"[异常] Backpack 下单请求失败: {e}")
        raise e
    logger.info(f"[Backpack] 下单结果: {order_result}")
    if not order_result or "Error" in order_result:
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
        fill_order = backpack_funding_client.get_fill_history(symbol=symbol, orderId=order_id)
        if not fill_order or "error" in fill_order:
            logger.info(f"查询Backpack订单失败: {fill_order.get('error', '未知错误') if fill_order else '无返回'}")
            break
        if fill_order and len(fill_order) > 0:
            logger.info(f"订单已成交: {order_id}")
            return True
        time.sleep(interval)
    logger.info(f"订单{order_id}未成交，准备取消")
    backpack_funding_client.cancel_open_order(symbol=symbol, orderId=order_id)
    return False


# 在backpack 上进行合约平仓（通过订单ID反向下单）,开仓后才可平仓，合约挂单未成交不算平仓
def close_backpack_position_by_order_id(symbol, order_id, backpack_qty=None, backpack_client=backpack_funding_client):
    """
    根据订单ID平仓：查询订单，获取参数，反向下单
    :param backpack_client:
    :param backpack_qty:
    :param symbol:
    :param order_id: 需平仓的订单ID
    """
    # 查询订单详情
    order_infos = backpack_client.get_fill_history(symbol=symbol, orderId=order_id)
    if not order_infos or "error" in order_infos:
        raise Exception(f"查询订单失败: {order_infos.get('error', '未知错误')}")
    order_info = order_infos[0]
    logger.info(f"[Backpack] 查询到订单信息: {order_info}")
    symbol = order_info["symbol"]
    side = order_info["side"]
    qty = order_info["quantity"] if backpack_qty is None else backpack_qty  # 如果传入了数量，则使用传入的数量，否则使用订单中的数量
    price = order_info["price"]
    # order_type = order_info.get("orderType", OrderType.MARKET)
    order_type = OrderType.MARKET  # 默认使用市价单平仓
    # 反向方向
    close_side = "short" if side == "Bid" else "long"
    # 平仓下单
    logger.info(f"[Backpack] 准备平仓: {symbol}, 方向: {close_side}, 数量: {qty}, 价格: {price}, 类型: {order_type}")
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
    logger.info(f"[Backpack] 平仓结果: {order_result}")
    if not order_result or "Error" in order_result:
        raise Exception(f"Backpack 平仓失败: {order_result.get('error', '未知错误')}")
    return order_result


# === 主套利逻辑 ===
def arbitrage_loop():
    is_open = False
    open_info = {}  # 保存开仓的信息（等待应应收益和平仓）

    while True:
        try:
            logger.info("\n==== 开始资金费率套利程序 ====")
            now = datetime.now()

            if not is_open:
                results = calculate_funding_rate_diff()
                # 筛选最大差值并且要求资金费率差大于阈值，无 hold，并在窗口期内
                for r in results:
                    if (
                            float(r["annualized"]) >= float(THRESHOLD_DIFF_Y)
                            and r["okx_action"] != "hold"
                            and r["backpack_action"] != "hold"
                            and within_funding_window(datetime.fromtimestamp(int(r["next_funding_time"]) / 1000),
                                                      SETTLEMENT_WINDOW_MIN)
                    ):
                        # 执行开仓前准备工作
                        logger.info("\n>> 开始执行开仓前准备...")
                        # 获取当前标的最新价格
                        okx_ticker = okx_market_api.get_ticker(instId=r["okx_symbol"])
                        okx_price = float(
                            okx_ticker["data"][0]["last"]) if okx_ticker and "data" in okx_ticker else None
                        backpack_ticker = backpack_public.get_ticker(r["backpack_symbol"])
                        backpack_price = float(backpack_ticker[
                                                   "lastPrice"]) if backpack_ticker and "lastPrice" in backpack_ticker \
                            else None
                        logger.info(f"OKX最新价: {okx_price}, Backpack最新价: {backpack_price}")
                        price = (okx_price + backpack_price) / 2 if okx_price and backpack_price else None

                        # 计算okx合约张数（先用calc_qty计算，再向下取整为最小张数的整数倍）
                        okx_ctval = float(SYMBOL_OKX_INSTRUMENT_MAP[r["okx_symbol"]]["ctVal"])  # 合约面值
                        okx_minsz = float(SYMBOL_OKX_INSTRUMENT_MAP[r["okx_symbol"]]["minsz"])  # 最小张数
                        raw_okx_qty = calc_qty((okx_price + backpack_price) / 2, MAX_ORDER_USD, MAX_LEVERAGE, okx_ctval)
                        okx_qty = int(raw_okx_qty // okx_minsz) * okx_minsz
                        okx_qty = round(okx_qty, 4)
                        # 根据okx_qty反推backpack_qty（币本位：张数 * 合约面值）
                        backpack_qty = round(okx_qty * okx_ctval, 4)
                        logger.info(f"计划开仓数量okx: {okx_qty}, 价格: {price}, backpack: {backpack_qty}")
                        if not price or okx_qty <= 0 or backpack_qty <= 0:
                            logger.info(
                                f"[异常] 计算开仓数量或价格失败: okx_qty={okx_qty}, backpack_qty={backpack_qty}, price={price}")
                            continue

                        # 平台开单逻辑，okx先尝试开单三次，成功则进行Backpack开单，不成功抛出异常，外层再重试一次
                        # backpack开单逻辑，okx开单成功后，检查订单是否成交，成交则进行Backpack开单，同样尝试三次
                        # 修正，调换顺序，先Backpack开单，成交后再开单okx，先开仓流动性差的
                        # continue
                        try:
                            # 子try catch 1: OKX下单
                            okx_result = {}
                            backpack_result = {}
                            for okx_attempt in range(3):
                                try:
                                    okx_result = execute_okx_order_swap(r["okx_symbol"], r["okx_action"], okx_qty,
                                                                        price)
                                    break
                                except Exception as okx_e:
                                    logger.info(f"[异常] OKX下单失败, 第{okx_attempt + 1}次重试: {okx_e}")
                                    if okx_attempt == 2:
                                        raise
                                    time.sleep(2)
                            # 子try catch 2: 检查OKX订单并Backpack下单
                            for bp_attempt in range(3):
                                try:
                                    if ((bp_attempt == 0 and
                                         check_okx_order_filled(r["okx_symbol"], okx_result["data"][0].get("ordId")))
                                            or bp_attempt > 0):
                                        backpack_result = execute_backpack_order(r["backpack_symbol"],
                                                                                 r["backpack_action"], backpack_qty,
                                                                                 price)
                                    break
                                except Exception as bp_e:
                                    logger.info(f"[异常] Backpack下单失败, 第{bp_attempt + 1}次重试: {bp_e}")
                                    if bp_attempt == 2:
                                        raise
                                    time.sleep(2)
                        except Exception as e:
                            logger.info(f"[异常] 执行开仓失败: {e}, 正在取消OKX和Backpack所有当前标的开单并重试...")
                            # 取消OKX当前标的所有开单，先关仓流动性好的，避免损失
                            try:
                                open_orders = okx_trade_api.get_order_list(instId=r["okx_symbol"])
                                if open_orders and open_orders.get("code") == "0":
                                    for order in open_orders["data"]:
                                        okx_trade_api.cancel_order(instId=r["okx_symbol"], ordId=order["ordId"])
                            except Exception as cancel_okx_e:
                                logger.info(f"[异常] 取消OKX开单失败: {cancel_okx_e}")
                            # 取消Backpack当前标的所有开单
                            try:
                                open_orders = backpack_funding_client.get_users_open_orders(symbol=r["backpack_symbol"])
                                if open_orders and isinstance(open_orders, list):
                                    for order in open_orders:
                                        backpack_funding_client.cancel_open_order(symbol=r["backpack_symbol"],
                                                                                  orderId=order["id"])
                            except Exception as cancel_bp_e:
                                logger.info(f"[异常] 取消Backpack开单失败: {cancel_bp_e}")
                            # 重试开仓
                            okx_result = execute_okx_order_swap(r["okx_symbol"], r["okx_action"], okx_qty, price)
                            backpack_result = execute_backpack_order(r["backpack_symbol"], r["backpack_action"],
                                                                     backpack_qty,
                                                                     price)
                        # 获取已开仓位的价值
                        okx_order_info = okx_trade_api.get_order(instId=r["okx_symbol"],
                                                                 ordId=okx_result["data"][0].get("ordId"))
                        if not okx_order_info or okx_order_info.get("code") != "0":
                            raise Exception(f"获取OKX订单信息失败: {okx_order_info.get('msg', '未知错误')}")

                        okx_fillsz = float(okx_order_info["data"][0]["fillSz"])  # 已成交数量
                        okx_avgPx = float(okx_order_info["data"][0]["avgPx"])  # 平均成交价格

                        # 开仓信息汇总
                        open_info = {
                            "okx_symbol": r["okx_symbol"],
                            "backpack_symbol": r["backpack_symbol"],
                            "okx_action": r["okx_action"],
                            "backpack_action": r["backpack_action"],
                            "entry_time": now,
                            "close_time": r["next_funding_time"],
                            "okx_order_id": okx_result["data"][0].get("ordId"),
                            "backpack_order_id": backpack_result.get("id"),
                            "okx_qty": okx_qty,
                            "backpack_qty": backpack_qty,
                        }
                        is_open = True
                        logger.info(f"\n>> 开仓成功: open_info={open_info}")
                        break  # 只执行一组
                    else:
                        logger.info(f"results annualized: {r['annualized']:.4%}  {THRESHOLD_DIFF_Y:.4%}, "
                              f"okx_action: {r['okx_action']}, "
                              f"backpack_action: {r['backpack_action']}, "
                              f"next_funding_time: {datetime.fromtimestamp(int(r['next_funding_time']) / 1000)},"
                              f"now: {datetime.now()}")

            else:
                # 已开仓，进行监控
                now_ts = int(datetime.now().timestamp() * 1000)
                logger.info(f"当前时间: {datetime.now()}, 关仓时间: {datetime.fromtimestamp(int(open_info['close_time']) / 1000)}")

                if now_ts >= int(open_info["close_time"]):
                    logger.info("\n>> 到达应收益时点，开始平仓")
                    time.sleep(40)  # 等待40秒，确保资金费率结算完成

                    close_okx_position_by_order_id(symbol=open_info["okx_symbol"],
                                                   order_id=open_info["okx_order_id"],
                                                   okx_qty=open_info["okx_qty"])
                    close_backpack_position_by_order_id(symbol=open_info["backpack_symbol"],
                                                        order_id=open_info["backpack_order_id"],
                                                        backpack_qty=open_info["backpack_qty"])
                    logger.info("[OKX]平仓", open_info["okx_symbol"])
                    logger.info("[Backpack]平仓", open_info["backpack_symbol"])

                    is_open = False
                    open_info = {}
                else:
                    logger.info(">> 未到结算时间，预估收益情况:")
                    # 计算预计获利
                    okx_symbol = open_info.get("okx_symbol")
                    backpack_symbol = open_info.get("backpack_symbol")

                    # 获取最新资金费率
                    try:
                        okx_rate, _, _ = get_okx_funding_rate(okx_public_api, okx_symbol)
                        backpack_rate, _ = get_backpack_funding_rate(backpack_public, backpack_symbol)
                        rate_diff = abs(okx_rate - backpack_rate)
                        # 资金费率为单边，套利为双边
                        # 预计收益 = 资金费率差 * 仓位
                        # 假设持有1个周期（8小时），年化换算：单次收益 * 3 * 365
                        profit = rate_diff * MAX_LEVERAGE * MAX_ORDER_USD
                        annualized = abs(rate_diff) * 3 * 365
                        logger.info(f"预计本周期获利: {profit:.2f} USDT, 年化: {annualized:.2%}")
                    except Exception as e:
                        logger.info(f"计算预计获利失败: {e}")

            if is_open:
                time.sleep(300)  # 每5分钟重试
            else:
                time.sleep(60*15)  # 每15分钟检查一次套利机会
        except Exception as e:
            logger.info("[异常]", e)
            logger.info("正在取消所有当前标的开单并重试...")
            if is_open:
                close_okx_position_by_order_id(symbol=open_info["okx_symbol"],
                                               order_id=open_info["okx_order_id"],
                                               okx_qty=open_info["okx_qty"])
                close_backpack_position_by_order_id(symbol=open_info["backpack_symbol"],
                                                    order_id=open_info["backpack_order_id"],
                                                    backpack_qty=open_info["backpack_qty"])
            break


if __name__ == "__main__":
    arbitrage_loop()
