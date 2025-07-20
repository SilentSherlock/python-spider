import random
import threading
import time

from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType, OrderSide, TimeInForce, MarketType

from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys_trade_cat_volume

proxy_on()

public_key, secret_key = load_backpack_api_keys_trade_cat_volume()
client = AuthenticationClient(public_key, secret_key)
public = PublicClient()
SYMBOL = "SOL_USDC"  # 交易标的
SYMBOLS = ["BTC_USDC", "ETH_USDC", "SOL_USDC", "XRP_USDC", "SUI_USDC"]
MIN_ORDER_USD = 30
MAX_ORDER_USD = 50
SLIPPAGE = 0.0001  # 0.01%
CHECK_INTERVAL = 5  # 秒
MAX_WAIT_COUNT = 10  # 最多轮询10次（大约40秒）
TEST_FLAG = False  # 是否为测试模式


def get_last_price(symbol_price=SYMBOL):
    """获取SOL/USDC的最新价格"""
    ticker = public.get_ticker(symbol_price)
    return float(ticker["lastPrice"])


def get_open_orders():
    """获取当前所有未完成的现货挂单"""
    return client.get_open_orders(symbol=SYMBOL, marketType=MarketType.SPOT)


def cancel_all_orders():
    """取消所有未完成的现货挂单"""
    client.cancel_open_orders(SYMBOL)


def order_exists_in_range(order_list, min_usd, max_usd):
    """检查是否有订单在指定的USD范围内"""
    for order in order_list:
        if order["symbol"] != SYMBOL:
            continue
        price = float(order["price"])
        qty = float(order["quantity"])
        usd_value = price * qty
        if min_usd <= usd_value <= max_usd:
            return True
    return False


def place_limit_order(order_symbol, price, qty, side):
    """执行挂单，实操"""
    print(f"挂{side}限价单: 数量={qty}, 价格={price}")
    return client.execute_order(
        orderType=OrderType.LIMIT,
        side=OrderSide.BID if side == "BUY" else OrderSide.ASK,
        symbol=order_symbol,
        price=str(price),
        quantity=str(qty),
        timeInForce=TimeInForce.GTC,
        postOnly=True
    )


def place_limit_order_test(price, qty, side):
    """测试挂单，随机返回一个order状态"""
    print(f"挂{side}限价单: 数量={qty}, 价格={price}")
    return {"id": str(random.randint(100000, 999999)), "status": "PENDING"}


def place_market_order(order_symbol, quantity, side):
    """执行吃单（市价单）"""
    print(f"吃{side}市价单: 数量={quantity}")
    return client.execute_order(
        orderType=OrderType.MARKET,
        side=OrderSide.BID if side == "BUY" else OrderSide.ASK,
        symbol=order_symbol,
        quantity=str(quantity),
        timeInForce=TimeInForce.IOC
    )


def wait_for_fill(order_id):
    for attempt in range(MAX_WAIT_COUNT):
        fills = client.get_fill_history(orderId=order_id, symbol=SYMBOL)
        if fills and len(fills) > 0:
            print(f"订单已成交: {order_id}")
            return True
        print(f"等待成交中...({attempt + 1}/{MAX_WAIT_COUNT})")
        time.sleep(CHECK_INTERVAL)
    print(f"订单未成交，准备撤单: {order_id}")
    client.cancel_open_order(SYMBOL, orderId=order_id)
    return False


def wait_for_fill_test(order_id):
    """以随机形式返回true或者false，true和false的比例大概为100:1"""
    for attempt in range(MAX_WAIT_COUNT):
        if random.random() < 0.5:  # 99%概率成交
            print(f"订单已成交: {order_id}")
            return True
        print(f"等待成交中...({attempt + 1}/{MAX_WAIT_COUNT})")
        time.sleep(CHECK_INTERVAL)
    print(f"订单未成交，准备撤单: {order_id}")
    return False


def check_balance(check_symbol, price, quantity, side, trade_type="SPOT"):
    """检查账户余额是否足够，足够，返回交易方向，不足够，返回False"""
    balances = client.get_balances()
    check_symbols = check_symbol.split("_")
    sol_balance = float(balances.get(check_symbols[0], {}).get("available", 0))
    usdc_balance = float(balances.get(check_symbols[1], {}).get("available", 0))
    usdc_need = round(price * quantity, 2)
    sol_need = round(quantity, 2)

    # sol的量和usdc的量均不足以进行交易
    if sol_need > sol_balance and usdc_need > usdc_balance:
        print(f"账户余额不足: SOL={sol_balance}, USDC={usdc_balance}, 需要: SOL={sol_need}, USDC={usdc_need}")
        return False

    # 买入或卖出均满足
    if side == "BUY" and usdc_need <= usdc_balance:
        print(f"账户余额足够进行买入: USDC={usdc_balance}, 需要={usdc_need}")
        return "BUY"
    if side == "SELL" and sol_need <= sol_balance:
        print(f"账户余额足够进行卖出: SOL={sol_balance}, 需要={sol_need}")
        return "SELL"

    # 现货买入或卖出不满足，进行反向交易, 布林带交易返回fase
    if trade_type == "SPOT":
        return "SELL" if side == "BUY" else "BUY"
    elif trade_type == "bollinger":
        return False


def get_kline(symbol, interval, start_time, end_time):
    """
    获取某个标的在某段时间的K线图
    :param symbol: 标的，如"BTC_USDC"
    :param interval: K线间隔，如"1m", "5m", "1h"
    :param start_time: 开始时间，时间戳（秒）
    :param end_time: 结束时间，时间戳（秒）
    :return: K线数据列表
    """
    return public.get_klines(
        symbol=symbol,
        interval=interval,
        start_time=start_time,
        end_time=end_time
    )


def calculate_bollinger_bands(kline_data, window=20, num_std=2):
    """
    根据给定的K线数据计算布林轨道
    :param kline_data: K线数据列表，每个元素为dict，需包含"close"字段
    :param window: 均线窗口大小，默认20
    :param num_std: 标准差倍数，默认2
    :return: 返回一个列表，每个元素为dict，包含'middle', 'upper', 'lower'
    """
    closes = [float(item["close"]) for item in kline_data]
    bands = []
    for i in range(window - 1, len(closes)):
        window_closes = closes[i - window + 1:i + 1]
        ma = sum(window_closes) / window
        std = (sum((x - ma) ** 2 for x in window_closes) / window) ** 0.5
        upper = ma + num_std * std
        lower = ma - num_std * std
        bands.append({
            "middle": round(ma, 6),
            "upper": round(upper, 6),
            "lower": round(lower, 6)
        })
    return bands


def run_volume_loop():
    # 预检查是否已有挂单在30-50U之间
    orders = get_open_orders()
    if order_exists_in_range(orders, 0, MAX_ORDER_USD):
        print("已有0-50U挂单，先取消所有挂单")
        cancel_all_orders()

    filled = True
    while True:
        try:
            # 买卖交替进行
            for side in ["BUY", "SELL"]:
                if not filled:
                    print(f"上一个订单未成交，跳过{side}操作")
                    filled = True
                    continue
                last_price = get_last_price(symbol)
                low_price = round(last_price * (1 - SLIPPAGE), 2)
                high_price = round(last_price * (1 + SLIPPAGE), 2)
                # base_price = low_price
                base_price = low_price if side == "BUY" else high_price

                usd_value = round(random.uniform(MIN_ORDER_USD, MAX_ORDER_USD), 2)
                quantity = round(usd_value / base_price, 2)
                print(
                    f"当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}, 下单价格: {base_price}, 下单数量: {quantity}, 方向: {side}")
                if not TEST_FLAG:
                    # 交易之前先判断当前单是否有足够流动性进行
                    check_result = check_balance(base_price, quantity, side)
                    if not check_result:
                        print("账户余额不足，结束线程")
                        return
                        # 挂单买入，吃单卖出
                    if check_result == "SELL":
                        # order = place_market_order(quantity, check_result)
                        order = place_limit_order(base_price, quantity, check_result)
                    else:
                        order = place_limit_order(base_price, quantity, check_result)
                else:
                    order = place_limit_order_test(base_price, quantity, side)
                order_id = order.get("id")

                if not order_id:
                    print("下单失败，跳过本轮")
                    continue

                if not TEST_FLAG:
                    filled = wait_for_fill(order_id)
                else:
                    filled = wait_for_fill_test(order_id)
                time.sleep(random.uniform(6, 10))  # 成交后等待

        except Exception as e:
            print(f"发生异常: {e}, 取消所有挂单")
            cancel_all_orders()
            time.sleep(5)


def bollinger_trade_loop(symbol="SOL_USDC"):
    interval = "15m"
    while True:
        try:
            end_time = int(time.time())
            start_time = end_time - 100 * 15 * 60  # 100根15mK线
            kline_data = get_kline(symbol, interval, start_time, end_time)
            if len(kline_data) < 20:
                print("K线数据不足，跳过本轮")
                time.sleep(1800)
                continue
            bands = calculate_bollinger_bands(kline_data)
            last_band = bands[-1]  # 获取最新的布林带数据
            last_price = get_last_price(symbol)
            print(f"当前价格: {last_price}, 布林带: {last_band}")
            if last_price <= last_band["lower"]:
                print("价格低于布林带下轨，买入")
                usd_value = round(random.uniform(MIN_ORDER_USD, MAX_ORDER_USD), 2)
                quantity = round(usd_value / last_price, 2)
                if not TEST_FLAG:
                    check_result = check_balance(symbol, last_price, quantity, "BUY", "bollinger")
                    if check_result == "BUY":
                        order = place_limit_order(symbol, last_price, quantity, "BUY")
                        order_id = order.get("id")
                        if order_id:
                            wait_for_fill(order_id)
                else:
                    order = place_limit_order_test(last_price, quantity, "BUY")
            elif last_price >= last_band["upper"]:
                print("价格高于布林带上轨，卖出")
                usd_value = round(random.uniform(MIN_ORDER_USD, MAX_ORDER_USD), 2)
                quantity = round(usd_value / last_price, 2)
                if not TEST_FLAG:
                    check_result = check_balance(symbol, last_price, quantity, "SELL", "bollinger")
                    if check_result == "SELL":
                        order = place_limit_order(last_price, quantity, "SELL")
                        order_id = order.get("id")
                        if order_id:
                            wait_for_fill(order_id)
                else:
                    order = place_limit_order_test(last_price, quantity, "SELL")
            else:
                print("价格在布林带区间内，暂不操作")
            time.sleep(1800)  # 30分钟
        except Exception as e:
            print(f"发生异常: {e}")
            time.sleep(60)


if __name__ == "__main__":

    # 布林带交易
    # bollinger_trade_loop(symbol=SYMBOL)
    # 布林带现货交易
    threads = []
    for symbol in SYMBOLS:
        t = threading.Thread(target=bollinger_trade_loop, args=(symbol,))
        t.start()
        time.sleep(random.uniform(8, 15))  # 随机等待8，15s
        threads.append(t)

    for t in threads:
        t.join()
