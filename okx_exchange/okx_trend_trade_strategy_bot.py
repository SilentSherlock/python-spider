import random
import threading
import time

import numpy as np
from enums.RequestEnums import OrderType
from okx import Account, Trade, Funding, PublicData, MarketData

from arbitrage_bot.backpack_okx_arbitrage_bot import execute_backpack_order, close_backpack_position_by_order_id
from backpack_exchange.sol_usdc_limit_volume_bot import get_kline
from backpack_exchange.trade_prepare import proxy_on, load_okx_api_keys_trade_cat_okx_trend
from okx_exchange.macd_signal import macd_signals

# 启用代理与加载密钥
proxy_on()
okx_live_trading = "0"
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys_trade_cat_okx_trend()
okx_account_api = Account.AccountAPI(
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_funding_api = Funding.FundingAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_public_api = PublicData.PublicAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_market_api = MarketData.MarketAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

SYMBOL = "SOL-USDT-SWAP"
TREND_SYMBOL_LIST = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "SUI-USDT-SWAP",
    "XRP-USDT-SWAP",
]

OKX_OPEN_INTERVAL_SEC = 5 * 60  # 每5分钟执行一次
MARGIN = 50  # 保证金
LEVERAGE = 15
LOSS_LIMIT = 0.2  # 亏损20%止损
PROFIT_DRAWBACK = 0.2  # 盈利回撤20%止盈保护


def monitor_position(okx_price, direction, order_id, okx_qty, leverage=LEVERAGE, monitor_symbol=SYMBOL):
    peak_price = okx_price
    price_history = [okx_price]

    while True:
        time.sleep(60)
        okx_ticker = okx_market_api.get_ticker(instId=monitor_symbol)
        current_price = float(
            okx_ticker["data"][0]["last"]) if okx_ticker and "data" in okx_ticker else None
        price_history.append(current_price)
        if len(price_history) > 6:
            price_history.pop(0)

        # 加上杠杆计算实际盈亏比例
        pnl = ((current_price - okx_price) / okx_price * leverage) if direction == 'long' \
            else ((okx_price - current_price) / okx_price * leverage)

        if direction == 'long':
            peak_price = max(peak_price, current_price)
        else:
            peak_price = min(peak_price, current_price)

        # 加上杠杆计算实际回撤比例
        draw_down = ((peak_price - current_price) / peak_price * leverage) if direction == 'long' \
            else ((current_price - peak_price) / peak_price * leverage)

        print(
            f"当前{monitor_symbol}价格: {current_price:.4f}, 下单价格:{okx_price}, direction: {direction} "
            f"杠杆盈亏: {pnl:.4%}, 杠杆回撤: {draw_down:.2%}")

        if pnl <= -0.2:
            print(f"止损触发，亏损金额: {(okx_price - current_price) * float(okx_qty):.4f} USDC")
            break
        if pnl > 0 and draw_down >= 0.3:
            print(f"盈利回撤触发，当前盈利: {abs((current_price - okx_price)) * float(okx_qty):.4f} USDC")
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
    # 计算盈亏
    profit = float(okx_qty) * (current_price - okx_price) if direction == 'long' \
        else float(okx_qty) * (okx_price - current_price)
    print(f"准备平仓: {monitor_symbol}, 方向: {direction}, 数量: {okx_qty}, "
          f"盈亏: {profit :.4f} USDC")
    close_backpack_position_by_order_id(monitor_symbol, order_id, okx_qty)


def fetch_kline_data(kline_symbol=SYMBOL, interval="5m", limit=30):
    """
    获取指定交易对的最新已经完结limit根K线数据，返回数据由新到旧排序，最新的K可能未结束
    :param kline_symbol: 交易对符号
    :param interval: K线周期
    :param limit: 返回的K线数量
    :return: K线数据列表
    """
    klines = okx_market_api.get_mark_price_candlesticks(instId=kline_symbol, bar=interval, limit=limit)
    if not klines or "data" not in klines or len(klines["data"]) < limit:
        raise Exception(f"获取K线数据失败: {klines.get('msg', '未知错误')}")
    klines_data = klines["data"]
    # if klines_data and klines_data[0][5] == "0":
    #     klines_data.pop(0)
    return klines_data


def monitor_position_macd(direction_symbol=SYMBOL):
    """
    计算指定交易对的最新MACD指标，进行开仓
    策略：
    策略每5分钟执行一次，设立标志位判断是否开仓，并记录开仓信息，信息包括订单id,方向，仓位数量
    获取k线数据，调用macd_signals计算最新的MACD指标
    若没有开仓，进入开仓判断：
    * 进行量化方向信号判断
    * 由量化信号判断代码返回的方向进行开单，开单方法留空，保留开单信息
    若开仓，进入持仓监控：
    * 进行关仓方向判断
    * 判断需要关单时，调用方法进行平仓
    :param direction_symbol:
    :return:
    """
    position = None  # 持仓信息，格式：{'order_id':..., 'direction':..., 'qty':...}
    while True:
        # time.sleep(OKX_OPEN_INTERVAL_SEC)
        klines = fetch_kline_data(kline_symbol=direction_symbol, interval="5m", limit=50)
        macd_signal = macd_signals(klines)
        if position is None:
            # 未持仓，判断是否开仓
            direction = None
            if macd_signal == "golden_cross":
                direction = "long"
            elif macd_signal == "death_cross":
                direction = "short"
            if direction:
                # 这里应调用开仓API，下单方法留空
                order_id = "mock_order_id"
                qty = MARGIN * LEVERAGE / close_prices[-1]
                position = {'order_id': order_id, 'direction': direction, 'qty': qty}
                print(f"开仓: 方向: {direction}, 数量: {qty}, 订单ID: {order_id}")
        else:
            # 已持仓，判断是否需要平仓
            close_signal = False
            if (position['direction'] == "long" and macd_signal == "death_cross") or \
                    (position['direction'] == "short" and macd_signal == "golden_cross"):
                close_signal = True
            if close_signal:
                print(f"平仓: 订单ID: {position['order_id']}, 方向: {position['direction']}, 数量: {position['qty']}")
                # 这里应调用平仓API
                position = None


# 两根15分钟k线判断方法
def get_open_direction_15mkline(kline_symbol=SYMBOL):
    # 两根15分钟k线判断
    now = time.localtime()
    end_time = int(
        time.mktime((now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min // 15 * 15, 0, 0, 0, -1))) * 1000
    start_time = end_time - 2 * 15 * 60 * 1000  # 转换为毫秒
    interval = "15m"
    klines = okx_market_api.get_mark_price_candlesticks(
        instId=kline_symbol, bar=interval, after=end_time, before=start_time, limit=2
    )
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



# if __name__ == "__main__":

