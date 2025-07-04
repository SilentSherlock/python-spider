import random
import time
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType, OrderSide, TimeInForce, MarketType

from backpack_exchange.trade_prepare import proxy_on, load_api_keys

proxy_on()

public_key, secret_key = load_api_keys()
client = AuthenticationClient(public_key, secret_key)
public = PublicClient()

SYMBOL = "SOL_USDC"
MIN_ORDER_USD = 30
MAX_ORDER_USD = 50
SLIPPAGE = 0.0001  # 0.01%
CHECK_INTERVAL = 5  # 秒
MAX_WAIT_COUNT = 8  # 最多轮询8次（大约40秒）
TEST_FLAG = True  # 是否为测试模式


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
        if random.random() < 0.99:  # 99%概率成交
            print(f"订单已成交: {order_id}")
            return True
        print(f"等待成交中...({attempt + 1}/{MAX_WAIT_COUNT})")
        time.sleep(CHECK_INTERVAL)
    print(f"订单未成交，准备撤单: {order_id}")
    return False


def run_volume_loop():
    # 预检查是否已有挂单在30-50U之间
    orders = get_open_orders()
    if order_exists_in_range(orders, 0, MAX_ORDER_USD):
        print("已有0-50U挂单，先取消所有挂单")
        cancel_all_orders()

    while True:
        try:
            # 买卖交替进行
            filled = True
            for side in ["BUY", "SELL"]:
                if not filled:
                    print(f"上一个订单未成交，跳过{side}操作")
                    filled = True
                    continue
                last_price = get_last_price()
                base_price = round(last_price * (1 - SLIPPAGE), 2) if side == "BUY" \
                    else round(last_price * (1 + SLIPPAGE), 2)
                # base_price = base_price if side == "SELL" else base_price - 0.01

                usd_value = round(random.uniform(MIN_ORDER_USD, MAX_ORDER_USD), 2)
                quantity = round(usd_value / base_price, 4)

                if not TEST_FLAG:
                    order = place_limit_order(base_price, quantity, side)
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
                time.sleep(random.randint(5, 8))  # 成交后等待

        except Exception as e:
            print(f"发生异常: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_volume_loop()
