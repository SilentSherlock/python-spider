import datetime
import threading
import time

import numpy as np
from enums.RequestEnums import OrderType
from okx import Account, Trade, Funding, PublicData, MarketData

from arbitrage_bot.backpack_okx_arbitrage_bot import close_backpack_position_by_order_id, \
    SYMBOL_OKX_INSTRUMENT_MAP, calc_qty, execute_okx_order_swap, close_okx_position_by_order_id
from backpack_exchange.trade_prepare import proxy_on, load_okx_api_keys_trade_cat_okx_trend, okx_account_api_test, \
    okx_trade_api_test, okx_market_api_test
from okx_exchange.macd_signal import macd_signals
from utils.logging_setup import setup_logger, setup_okx_macd_logger

# 启用代理与加载密钥
proxy_on()
logger = setup_logger(__name__)
okx_trade_macd_logger = setup_okx_macd_logger()

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

OKX_OPEN_INTERVAL_SEC = 5 * 60  # 每15分钟执行一次
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


def fetch_kline_data(market_api=okx_market_api, kline_symbol=SYMBOL, interval="5m", limit=30):
    """
    获取指定交易对的最新已经完结limit根K线数据，返回数据由新到旧排序，最新的K可能未结束
    :param market_api:
    :param kline_symbol: 交易对符号
    :param interval: K线周期
    :param limit: 返回的K线数量
    :return: K线数据列表
    """
    klines = market_api.get_mark_price_candlesticks(instId=kline_symbol, bar=interval, limit=limit)
    if not klines or "data" not in klines or len(klines["data"]) < limit:
        raise Exception(f"获取K线数据失败: {klines.get('msg', '未知错误')}")
    klines_data = klines["data"]
    if klines_data and klines_data[0][5] == "0":
        klines_data.pop(0)
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
    # 整15启动，以便获取完结的K线，同时尽可能避免数据损失
    # 延迟到最近的整15分钟再启动
    interval = 5
    now = datetime.datetime.now()
    delay_minutes = (interval - now.minute % interval) % interval
    delay_seconds = (delay_minutes * 60 - now.second) + 40  # 多等40秒，确保K线完结
    if delay_seconds > 0:
        logger.info(f"延迟 {delay_seconds} 秒，等待到最近的整{interval}分钟再启动")
        time.sleep(delay_seconds)

    while True:
        logger.info("开始新一轮信号计算")
        klines_interval = str(interval) + "m"
        klines = fetch_kline_data(market_api=okx_market_api_test, kline_symbol=direction_symbol, interval=klines_interval, limit=50)
        macd_signal = macd_signals(klines)

        macd_signal_target = {}
        for key in macd_signal.iloc[-1].keys():
            v1 = macd_signal.iloc[-1][key]
            v2 = macd_signal.iloc[-2][key]
            v3 = macd_signal.iloc[-3][key]
            if isinstance(v1, bool) and isinstance(v2, bool) and isinstance(v3, bool):
                macd_signal_target[key] = v1 ^ v2 ^ v3
            else:
                macd_signal_target[key] = v1
        # mack_signal_target = macd_signal.iloc[-1] ^ macd_signal.iloc[-2] ^ macd_signal.iloc[-3]  # 取最新三根k线的信号异或
        # print(macd_signal)
        # for m in macd_signal.iloc:
        #     print(m)
        logger.info(f"当前信号:{macd_signal_target}")
        # 低位金叉信息
        long_signal_1 = macd_signal_target["golden_cross"] and (macd_signal_target["DIF"] < 0)
        # 强势启动信号
        long_signal_2 = macd_signal_target["zero_up"] and macd_signal_target["hist_expanding"] and (
            not macd_signal_target['lines_converge'])
        # 反转抄底信号
        long_signal_3 = macd_signal_target["bullish_div"] and macd_signal_target["hist_red_to_green"]
        # 低位金叉+反转
        long_signal_4 = long_signal_1 and macd_signal_target["hist_red_to_green"]
        # ema金叉+低位金叉
        long_signal_5 = macd_signal_target["ema_golden_cross"] and long_signal_1

        # 高位死叉信息
        short_signal_1 = macd_signal_target["death_cross"] and (macd_signal_target["DIF"] > 0)
        # 强势启动信号
        short_signal_2 = macd_signal_target["zero_down"] and macd_signal_target["hist_expanding"]
        # 反转抄底信号
        short_signal_3 = macd_signal_target["bearish_div"] and macd_signal_target["hist_green_to_red"]
        # 高位死叉+反转
        short_signal_4 = short_signal_1 and macd_signal_target["hist_green_to_red"]
        # 高位死叉+ema死叉
        short_signal_5 = macd_signal_target["ema_death_cross"] and short_signal_1

        if position is None:
            logger.info("当前无持仓，进行开仓判断")
            direction = None
            # direction = "short"
            if long_signal_2 or (long_signal_1 and long_signal_3) or long_signal_4 or long_signal_5:
                direction = "long"
            elif short_signal_2 or (short_signal_1 and short_signal_3) or short_signal_4 or short_signal_5:
                direction = "short"

            if direction is None:
                logger.info("无开仓信号，继续等待")
            else:
                logger.info("开仓信号出现，准备开仓，方向: " + direction)
                okx_trade_macd_logger.info("开仓macd_signal: " + str(macd_signal_target))
                okx_trade_macd_logger.info(f"long_signal_2: {long_signal_2}, long_signal_1: {long_signal_1}, "
                                           f"long_signal_3: {long_signal_3}, long_signal_4: {long_signal_4}, "
                                           f"long_signal_5: {long_signal_5}, short_signal_2: {short_signal_2}, "
                                           f"short_signal_1: {short_signal_1}, short_signal_3: {short_signal_3}, "
                                           f"short_signal_4: {short_signal_4}, short_signal_5: {short_signal_5}")
                ticker_price = float(klines[0][4])  # 最新k线的收盘价
                # 计算开仓数量
                okx_ctval = float(SYMBOL_OKX_INSTRUMENT_MAP[direction_symbol]["ctVal"])  # 合约面值
                okx_minsz = float(SYMBOL_OKX_INSTRUMENT_MAP[direction_symbol]["minsz"])  # 最小张数
                raw_okx_qty = calc_qty(ticker_price / 2, MARGIN, LEVERAGE, okx_ctval)
                okx_qty = int(raw_okx_qty // okx_minsz) * okx_minsz
                okx_qty = round(okx_qty, 4)
                # 执行开仓
                okx_result = {}
                for attempt in range(3):
                    try:
                        okx_result = execute_okx_order_swap(
                            direction_symbol, direction, okx_qty, ticker_price,
                            order_type="market", account_api=okx_account_api_test,
                            trade_api=okx_trade_api_test, )
                        break
                    except Exception as okx_e:
                        if attempt == 2:
                            raise
                        time.sleep(2)
                position = {
                    "okx_symbol": direction_symbol,
                    "okx_action": "open",
                    "okx_order_id": okx_result['data'][0]['ordId'],
                    "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "okx_qty": okx_qty,
                    "okx_direction": direction,
                }
                logger.info(f"开仓: 订单ID: {position['okx_order_id']}, 方向: {direction}, 数量: {okx_qty}, ")
        else:
            # 已持仓，判断是否需要平仓
            close_flag = False
            # close_flag = True
            if "long" == position.get("okx_direction"):
                if (short_signal_2 or short_signal_1 or short_signal_3 or short_signal_4 or short_signal_5
                        or macd_signal_target["zero_down"] or macd_signal_target["death_cross"]):
                    close_flag = True
            elif "short" == position.get("okx_direction"):
                if long_signal_2 or long_signal_1 or long_signal_3 or long_signal_4 or long_signal_5\
                        or macd_signal_target["zero_up"] or macd_signal_target["golden_cross"]:
                    close_flag = True
            if close_flag:
                close_okx_position_by_order_id(symbol=position["okx_symbol"],
                                               order_id=position["okx_order_id"],
                                               okx_qty=position["okx_qty"],
                                               trade_api=okx_trade_api_test)
                position = None
                logger.info("平仓完成，等待下一次开仓信号")
            else:
                logger.info("持仓中，等待下一次平仓信号 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        time.sleep(OKX_OPEN_INTERVAL_SEC)


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


if __name__ == "__main__":
    threads = []
    for SYMBOL in TREND_SYMBOL_LIST:
        t = threading.Thread(target=monitor_position_macd, args=(SYMBOL,), name=f"Thread-{SYMBOL}")
        t.start()
        time.sleep(40)
        threads.append(t)
    for t in threads:
        t.join()
    # monitor_position_macd(direction_symbol=SYMBOL)
