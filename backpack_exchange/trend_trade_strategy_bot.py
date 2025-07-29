import random
import threading
import time
import math
import numpy as np
import talib
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType

from arbitrage_bot.backpack_okx_arbitrage_bot import execute_backpack_order, close_backpack_position_by_order_id
from backpack_exchange.sol_usdc_limit_volume_bot import get_kline
from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys_trade_cat_funding
from backpack_exchange.trend_trade_strategy_ema_bot import monitor_position_with_ema_exit

# 启用代理与加载密钥
proxy_on()
public_key, secret_key = load_backpack_api_keys_trade_cat_funding()
client = AuthenticationClient(public_key, secret_key)
public = PublicClient()

SYMBOL = "SOL_USDC_PERP"
TREND_SYMBOL_LIST = [
    "BTC_USDC_PERP",
    "ETH_USDC_PERP",
    "SOL_USDC_PERP",
    "SUI_USDC_PERP",
    "XRP_USDC_PERP",
]

OPEN_INTERVAL_SEC = 5 * 60  # 每5分钟执行一次
MARGIN = 50  # 保证金
LEVERAGE = 15
LOSS_LIMIT = -0.02  # 亏损2%止损
PROFIT_LIMIT = 0.05  # 盈利5%止盈
PROFIT_DRAWBACK = 0.1  # 盈利回撤10%止盈保护


def monitor_position(backpack_price, direction, order_id, backpack_qty, leverage=LEVERAGE, monitor_symbol=SYMBOL):
    price_history = [backpack_price]
    max_pnl = 0  # 记录最高盈利百分比（含杠杆）
    monitor_interval = 25  # 监控间隔时间（秒）
    monitor_points = 9  # 监控点数量

    while True:
        time.sleep(monitor_interval)
        current_price = float(public.get_ticker(monitor_symbol)['lastPrice'])
        price_history.append(current_price)
        if len(price_history) > monitor_points:
            price_history.pop(0)

        # 当前盈亏（含杠杆）
        pnl = ((current_price - backpack_price) / backpack_price * leverage) if direction == 'long' \
            else ((backpack_price - current_price) / backpack_price * leverage)

        # 更新最高盈利
        max_pnl = max(max_pnl, pnl)

        # 盈利回撤（绝对值）
        draw_down = max_pnl - pnl

        print(
            f"当前{monitor_symbol}价格: {current_price:.4f}, 下单价格:{backpack_price}, direction: {direction} "
            f"杠杆盈亏: {pnl:.4%}, 历史最高盈亏: {max_pnl:.4%}, 当前回撤: {draw_down:.4%}")

        # 固定止损：大幅亏损触发强平
        if pnl <= LOSS_LIMIT:
            print(f"止损触发，亏损金额: {(backpack_price - current_price) * float(backpack_qty):.4f} USDC")
            break

        # 固定止盈
        if pnl >= PROFIT_LIMIT:
            print(f"止盈触发，盈利金额: {abs(current_price - backpack_price) * float(backpack_qty):.4f} USDC")
            break

        # 盈利超过4%，启动“降半止损”
        if max_pnl >= 0.04:
            stop_drawdown = math.ceil((max_pnl / 2) * 100) / 100  # 向上取整到小数点后两位
            if draw_down >= stop_drawdown:
                print(f"盈利降半止损触发：最高盈亏 {max_pnl:.2%} 回撤 {draw_down:.2%} >= 限制 {stop_drawdown:.2%}")
                break

        # 趋势判断平仓
        if len(price_history) == monitor_points:
            x = list(range(monitor_points))
            y = price_history
            k, _ = np.polyfit(x, y, 1)
            if (direction == 'long' and k < 0) or (direction == 'short' and k > 0):
                print("最近六次价格趋势与持仓方向相反，平仓")
                break
            if abs(k) < 0.001:
                print("最近六次价格曲线趋向于直线，平仓")
                break

    # 平仓并打印盈亏
    profit = float(backpack_qty) * (current_price - backpack_price) if direction == 'long' \
        else float(backpack_qty) * (backpack_price - current_price)
    print(f"准备平仓: {monitor_symbol}, 方向: {direction}, 数量: {backpack_qty}, 盈亏: {profit:.4f} USDC")
    close_backpack_position_by_order_id(monitor_symbol, order_id, backpack_qty)


# 两根15分钟k线判断方法
def get_open_direction_15mkline(kline_symbol=SYMBOL):
    # 两根15分钟k线判断
    now = time.localtime()
    end_time = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min // 15 * 15, 0, 0, 0, -1)))
    start_time = end_time - 2 * 15 * 60
    interval = "15m"
    klines = get_kline(kline_symbol, interval, start_time, end_time)
    k1, k2 = klines[-2], klines[-1]
    up = float(k1['close']) > float(k1['open']) and float(k2['close']) > float(k2['open'])
    down = float(k1['close']) < float(k1['open']) and float(k2['close']) < float(k2['open'])
    print(
        f"15分钟K线判断: symbol: {kline_symbol} k1 open:{k1['open']}, k1 close:{k1['close']}, k2 open:{k2['open']}, k2 close：{k2['close']}"
        f", up: {up}, down: {down}")
    if up:
        return "long"
    elif down:
        return "short"
    else:
        return False


# 获取K线数据，默认返回30根15分钟K线
def fetch_klines(symbol, interval="15m"):
    end_time = int(time.time())  # 当前时间戳，单位秒
    start_time = end_time - 30 * 15 * 60  # 30根15分钟K线
    kline_data = public.get_klines(symbol, interval, start_time, end_time)
    closes = np.array([float(k["close"]) for k in kline_data])
    volumes = np.array([float(k["volume"]) for k in kline_data])
    return closes, volumes


# 策略 1：均线突破 + 放量确认
def ma_volume_strategy(symbol, volume_flag=False):
    closes, volumes = fetch_klines(symbol)

    ema9 = talib.EMA(closes, timeperiod=9)
    ema26 = talib.EMA(closes, timeperiod=26)

    # 金叉
    if ema9[-2] < ema26[-2] and ema9[-1] > ema26[-1]:
        if volume_flag and volumes[-1] > np.mean(volumes[-6:-1]):
            return "long"
        else:
            return "long"

    # 死叉
    if ema9[-2] > ema26[-2] and ema9[-1] < ema26[-1]:
        if volume_flag and volumes[-1] > np.mean(volumes[-6:-1]):
            return "short"
        else:
            return "short"

    return False


# 策略 2：MACD 金叉/死叉 + 放量确认
def macd_volume_strategy(symbol):
    closes, volumes = fetch_klines(symbol)

    macd, signal, _ = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)

    # 金叉
    if macd[-2] < signal[-2] and macd[-1] > signal[-1]:
        if volumes[-1] > np.mean(volumes[-6:-1]):
            return "long"

    # 死叉
    if macd[-2] > signal[-2] and macd[-1] < signal[-1]:
        if volumes[-1] > np.mean(volumes[-6:-1]):
            return "short"

    return False


def run_backpack_strategy(run_symbol,
                          direction_detector
                          ):
    in_position = False

    backpack_order_id = None
    backpack_qty = None
    while True:
        try:
            direction = None
            if direction_detector == "get_open_direction_15mkline":
                direction = get_open_direction_15mkline(run_symbol)
            elif direction_detector == "ma_volume_strategy":
                direction = ma_volume_strategy(run_symbol)
            # direction = ma_volume_strategy(run_symbol)
            if in_position:
                print("已有持仓，跳过开仓")
            else:
                backpack_ticker = public.get_ticker(run_symbol)
                backpack_price = float(backpack_ticker[
                                           "lastPrice"]) if backpack_ticker and "lastPrice" in backpack_ticker \
                    else None
                if not backpack_price:
                    print(f"无法获取backpack {run_symbol}价格，跳过本轮")
                    time.sleep(OPEN_INTERVAL_SEC)
                    continue
                if direction is False:
                    print(f"当前{run_symbol}无明确开仓信号，等待下一周期")
                    time.sleep(OPEN_INTERVAL_SEC)
                    continue
                backpack_qty = str(round((MARGIN * LEVERAGE) / backpack_price, 2))
                backpack_result = execute_backpack_order(run_symbol, direction, backpack_qty, str(backpack_price),
                                                         OrderType.MARKET,
                                                         leverage=LEVERAGE)
                backpack_order_id = backpack_result.get('id')
                in_position = True
                if direction_detector == "get_open_direction_15mkline":
                    monitor_position(backpack_price, direction, backpack_order_id, backpack_qty, LEVERAGE, run_symbol)
                elif direction_detector == "ma_volume_strategy":
                    monitor_position_with_ema_exit(backpack_price, direction, backpack_order_id, backpack_qty,
                                                   LEVERAGE, run_symbol)
                backpack_order_id = None
                backpack_qty = None
                in_position = False
        except Exception as e:
            print(f"异常: {e}, 若有持仓进行平仓处理")
            close_backpack_position_by_order_id(run_symbol, backpack_order_id, backpack_qty)
            in_position = False
        time.sleep(OPEN_INTERVAL_SEC)


if __name__ == "__main__":
    # run_backpack_strategy(run_symbol=SYMBOL,
    #                       direction_detector=get_open_direction_15mkline,
    #                       direction_detector_args=(SYMBOL,)
    #                       )
    threads = []
    for symbol in TREND_SYMBOL_LIST:
        print(f"开始进行 {symbol} 的趋势交易策略")
        t = threading.Thread(target=run_backpack_strategy,
                             args=(symbol, "get_open_direction_15mkline"),
                             name=f"TrendTradeStrategy-{symbol}")
        t.start()
        time.sleep(random.uniform(60, 90))
        threads.append(t)

    for t in threads:
        t.join()
