import random
import threading
import time

from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType, OrderSide, TimeInForce, MarketType

from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys_trade_cat

proxy_on()

public_key, secret_key = load_backpack_api_keys_trade_cat()
client = AuthenticationClient(public_key, secret_key)
public = PublicClient()

SYMBOL = "SOL_USDC"
MIN_ORDER_USD = 30
MAX_ORDER_USD = 50
SLIPPAGE = 0.0001  # 0.01%
CHECK_INTERVAL = 5  # 秒
MAX_WAIT_COUNT = 10  # 最多轮询10次（大约40秒）
TEST_FLAG = False  # 是否为测试模式


def get_last_price():
    """获取SOL/USDC的最新价格"""
    ticker = public.get_ticker(SYMBOL)
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


def place_limit_order(price, qty, side):
    """执行挂单，实操"""
    print(f"挂{side}限价单: 数量={qty}, 价格={price}")
    return client.execute_order(
        orderType=OrderType.LIMIT,
        side=OrderSide.BID if side == "BUY" else OrderSide.ASK,
        symbol=SYMBOL,
        price=str(price),
        quantity=str(qty),
        timeInForce=TimeInForce.GTC,
        postOnly=True
    )


def place_limit_order_test(price, qty, side):
    """测试挂单，随机返回一个order状态"""
    print(f"挂{side}限价单: 数量={qty}, 价格={price}")
    return {"id": str(random.randint(100000, 999999)), "status": "PENDING"}


def place_market_order(quantity, side):
    """执行吃单（市价单）"""
    print(f"吃{side}市价单: 数量={quantity}")
    return client.execute_order(
        orderType=OrderType.MARKET,
        side=OrderSide.BID if side == "BUY" else OrderSide.ASK,
        symbol=SYMBOL,
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


def check_balance(price, quantity, side):
    """检查账户余额是否足够，足够，返回交易方向，不足够，返回False"""
    balances = client.get_balances()
    sol_balance = float(balances.get("SOL", {}).get("available", 0))
    usdc_balance = float(balances.get("USDC", {}).get("available", 0))
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

    # 买入或卖出不满足，进行反向交易
    return "SELL" if side == "BUY" else "BUY"


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
                last_price = get_last_price()
                low_price = round(last_price * (1 - SLIPPAGE), 2)
                high_price = round(last_price * (1 + SLIPPAGE), 2)
                # base_price = low_price
                base_price = low_price if side == "BUY" else high_price

                usd_value = round(random.uniform(MIN_ORDER_USD, MAX_ORDER_USD), 2)
                quantity = round(usd_value / base_price, 2)
                print(f"当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}, 下单价格: {base_price}, 下单数量: {quantity}, 方向: {side}")
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


if __name__ == "__main__":

    threads = []
    for _ in range(1):
        t = threading.Thread(target=run_volume_loop, name=f"VolumeThread-{_ + 1}")
        t.start()
        time.sleep(random.uniform(8, 15))  # 随机等待8，15s
        threads.append(t)

    for t in threads:
        t.join()
