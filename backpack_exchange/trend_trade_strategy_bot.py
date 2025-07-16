import time
import numpy as np
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType, OrderSide, TimeInForce

from arbitrage_bot.backpack_okx_arbitrage_bot import execute_backpack_order, close_backpack_position_by_order_id
from backpack_exchange.sol_usdc_limit_volume_bot import get_kline
from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys_trade_cat_funding

# 启用代理与加载密钥
proxy_on()
public_key, secret_key = load_backpack_api_keys_trade_cat_funding()
client = AuthenticationClient(public_key, secret_key)
public = PublicClient()

SYMBOL = "SOL_USDC_PERP"
WINDOW_short = 4
WINDOW_long = 8
OPEN_INTERVAL_SEC = 5 * 60  # 每5分钟执行一次
MARGIN = 30  # 保证金
LEVERAGE = 10
LOSS_LIMIT = 0.2  # 亏损20%止损
PROFIT_DRAWBACK = 0.2  # 盈利回撤20%止盈保护


def monitor_position(backpack_price, direction, order_id, backpack_qty, leverage=LEVERAGE):
    peak_price = backpack_price
    price_history = [backpack_price]

    while True:
        time.sleep(60)
        current_price = float(public.get_ticker(SYMBOL)['lastPrice'])
        price_history.append(current_price)
        if len(price_history) > 6:
            price_history.pop(0)

        # 加上杠杆计算实际盈亏比例
        pnl = ((current_price - backpack_price) / backpack_price * leverage) if direction == 'long' \
            else ((backpack_price - current_price) / backpack_price * leverage)

        if direction == 'long':
            peak_price = max(peak_price, current_price)
        else:
            peak_price = min(peak_price, current_price)

        # 加上杠杆计算实际回撤比例
        drawdown = ((peak_price - current_price) / peak_price * leverage) if direction == 'long' \
            else ((current_price - peak_price) / peak_price * leverage)

        print(
            f"当前价格: {current_price:.4f}, 杠杆盈亏: {pnl:.4%}, 杠杆回撤: {drawdown:.2%}")

        if pnl <= -0.2:
            print(f"止损触发，亏损金额: {(backpack_price - current_price) * float(backpack_qty):.4f} USDC")
            break
        if pnl > 0 and drawdown >= 0.3:
            print(f"盈利回撤触发，当前盈利: {abs((current_price - backpack_price)) * float(backpack_qty):.4f} USDC")
            break

        # 判断最近六个价格的趋势
        if len(price_history) == 6:
            x = list(range(6))
            y = price_history
            # 线性拟合，获取斜率
            k, _ = np.polyfit(x, y, 1)
            # 判断趋势与方向相反
            if (direction == 'long' and k < 0) or (direction == 'short' and k > 0):
                print("最近六次价格趋势与持仓方向相反，平仓")
                break
            # 判断趋势趋向于直线（斜率接近0）
            if abs(k) < 0.001:
                print("最近六次价格曲线趋向于直线，平仓")
                break
    # 关仓
    close_backpack_position_by_order_id(SYMBOL, order_id, backpack_qty)


# 两根15分钟k线判断方法
def get_open_direction_15mkline():
    # 两根15分钟k线判断
    now = time.localtime()
    end_time = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min // 15 * 15, 0, 0, 0, -1)))
    start_time = end_time - 2 * 15 * 60
    interval = "15m"
    klines = get_kline(SYMBOL, interval, start_time, end_time)
    k1, k2 = klines[-2], klines[-1]
    up = float(k1['close']) > float(k1['open']) and float(k2['close']) > float(k2['open'])
    down = float(k1['close']) < float(k1['open']) and float(k2['close']) < float(k2['open'])
    print(f"15分钟K线判断: k1 high:{k1['high']}, k1 low:{k1['low']}, k2 high:{k2['high']}, k2 low{k2['low']}"
          f", up: {up}, down: {down}")
    if up:
        return "long"
    elif down:
        return "short"
    else:
        return False


def run_strategy():
    in_position = False

    while True:
        try:
            direction = get_open_direction_15mkline()
            if in_position:
                print("已有持仓，跳过开仓")
            else:
                backpack_ticker = public.get_ticker(SYMBOL)
                backpack_price = float(backpack_ticker[
                                           "lastPrice"]) if backpack_ticker and "lastPrice" in backpack_ticker \
                    else None
                if not backpack_price:
                    print(f"无法获取backpack {SYMBOL}价格，跳过本轮")
                    time.sleep(OPEN_INTERVAL_SEC)
                    continue
                if direction is False:
                    print("当前无明确开仓信号，等待下一周期")
                    time.sleep(OPEN_INTERVAL_SEC)
                    continue
                backpack_qty = str(round((MARGIN * LEVERAGE) / backpack_price, 2))
                backpack_result = execute_backpack_order(SYMBOL, direction, backpack_qty, str(backpack_price),
                                                         OrderType.MARKET,
                                                         leverage=LEVERAGE)
                backpack_order_id = backpack_result.get('id')
                in_position = True
                monitor_position(backpack_price, "long", backpack_order_id, backpack_qty)
                in_position = False
        except Exception as e:
            print(f"异常: {e}")

        time.sleep(OPEN_INTERVAL_SEC)


if __name__ == "__main__":
    run_strategy()
