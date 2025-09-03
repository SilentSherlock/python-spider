import datetime
import threading
import time

from arbitrage_bot.backpack_okx_arbitrage_bot import SYMBOL_OKX_INSTRUMENT_MAP, calc_qty, execute_okx_order_swap, \
    close_okx_position_by_order_id
from backpack_exchange.trade_prepare import proxy_on, okx_account_api_test, \
    okx_trade_api_test, okx_market_api_test, okx_market_api, okx_account_api, okx_trade_api
from okx_exchange.macd_signal import macd_signals, macd_signals_5m
from utils.logging_setup import setup_logger, setup_okx_macd_logger

# 启用代理与加载密钥
proxy_on()
logger = setup_logger(__name__)
okx_trade_macd_logger = setup_okx_macd_logger()

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
WIN_LIMIT_5k = 0.05  # 盈利10%止盈


def fetch_kline_data(market_api=okx_market_api_test, kline_symbol=SYMBOL, interval="5m", limit=30):
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


def monitor_position_macd(direction_symbol=SYMBOL,
                          account_api=okx_account_api_test,
                          trade_api=okx_trade_api_test,
                          market_api=okx_market_api_test,
                          k_rate=5):
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
    :param k_rate: 交易频率，单位分钟
    :param market_api:
    :param trade_api:
    :param account_api:
    :param direction_symbol:
    :return:
    """
    position = None  # 持仓信息，格式：{'order_id':..., 'direction':..., 'qty':...}
    # 整15启动，以便获取完结的K线，同时尽可能避免数据损失
    # 延迟到最近的整15分钟再启动
    interval = k_rate
    now = datetime.datetime.now()
    delay_minutes = (interval - now.minute % interval) % interval
    delay_seconds = (delay_minutes * 60 - now.second) + 10  # 多等40秒，确保K线完结
    if delay_seconds > 0:
        logger.info(f"延迟 {delay_seconds} 秒，等待到最近的整{interval}分钟再启动")
        time.sleep(delay_seconds)

    while True:
        logger.info("开始新一轮信号计算")
        klines_interval = str(interval) + "m"
        if interval == 60:
            klines_interval = "1H"
        try:
            klines = fetch_kline_data(market_api=market_api, kline_symbol=direction_symbol, interval=klines_interval,
                                      limit=50)
            macd_signal = macd_signals_5m(klines)

            macd_signal_target = {}
            for key in macd_signal.iloc[-1].keys():
                v1 = macd_signal.iloc[-1][key]
                v2 = macd_signal.iloc[-2][key]
                v3 = macd_signal.iloc[-3][key]
                if isinstance(v1, bool) and isinstance(v2, bool) and isinstance(v3, bool):
                    macd_signal_target[key] = v1 ^ v2 ^ v3
                else:
                    macd_signal_target[key] = v1

            logger.info(f"当前信号:{macd_signal_target}")
            # 低位金叉信息
            long_signal_1 = macd_signal_target["golden_cross"] and (macd_signal_target["DIF"] < 0)
            # 强势启动信号
            long_signal_2 = macd_signal_target["zero_up"] and macd_signal_target["hist_expanding"] and (
                not macd_signal_target['lines_converge'])
            # 反转抄底信号
            long_signal_3 = macd_signal_target["bullish_div"] and macd_signal_target["hist_red_to_green"]
            # 低位金叉+反转+非收敛
            long_signal_4 = (long_signal_1 and macd_signal_target["hist_red_to_green"]
                             and (not macd_signal_target["lines_converge"]))
            # ema金叉+低位金叉+非收敛
            long_signal_5 = macd_signal_target["ema_golden_cross"] and long_signal_1 \
                            and (not macd_signal_target["lines_converge"])

            # 高位死叉信息
            short_signal_1 = macd_signal_target["death_cross"] and (macd_signal_target["DIF"] > 0)
            # 强势启动信号
            short_signal_2 = macd_signal_target["zero_down"] and macd_signal_target["hist_expanding"]
            # 反转抄底信号
            short_signal_3 = macd_signal_target["bearish_div"] and macd_signal_target["hist_green_to_red"]
            # 高位死叉+反转+非收敛
            short_signal_4 = short_signal_1 and macd_signal_target["hist_green_to_red"] and (
                not macd_signal_target["lines_converge"])
            # 高位死叉+ema死叉+非收敛
            short_signal_5 = macd_signal_target["ema_death_cross"] and short_signal_1 and (
                not macd_signal_target["lines_converge"])

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
                    raw_okx_qty = calc_qty(ticker_price, MARGIN, LEVERAGE, okx_ctval)
                    okx_qty = int(raw_okx_qty // okx_minsz) * okx_minsz
                    okx_qty = round(okx_qty, 4)
                    # 执行开仓
                    okx_result = {}
                    for attempt in range(3):
                        try:
                            okx_result = execute_okx_order_swap(
                                direction_symbol, direction, okx_qty, ticker_price,
                                order_type="market", account_api=account_api,
                                trade_api=trade_api, )
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
                        "okx_entry_price": None,  # 开仓均价，后续更新
                    }
                    logger.info(f"开仓: 订单ID: {position['okx_order_id']}, 方向: {direction}, 数量: {okx_qty}, ")
            else:
                close_flag = False

                # 已持仓，计算大概盈亏
                if position["okx_entry_price"] is None:
                    order_info = trade_api.get_order(instId=position["okx_symbol"], ordId=position["okx_order_id"])
                    if order_info.get("code") == "0" and order_info.get("data"):
                        order_info_data = order_info["data"][0]
                        avg_px = float(order_info_data.get("avgPx", "0"))
                        position["okx_entry_price"] = avg_px if avg_px > 0 else position["okx_entry_price"]  # 更新为实际成交均价
                if position["okx_entry_price"] is not None:
                    okx_ticker = market_api.get_ticker(position["okx_symbol"])
                    okx_price = float(
                        okx_ticker["data"][0]["last"]) if okx_ticker and "data" in okx_ticker else None
                    if okx_price:
                        if position["okx_direction"] == "long":
                            change_pct = (okx_price - position["okx_entry_price"]) / position["okx_entry_price"]
                        elif position["okx_direction"] == "short":
                            change_pct = (position["okx_entry_price"] - okx_price) / position["okx_entry_price"]
                        else:
                            change_pct = 0
                        logger.info(f"持仓中，当前价格: {okx_price}, 开仓均价: {position['okx_entry_price']}, "
                                    f"浮动盈亏: {change_pct:.4%}")
                        okx_trade_macd_logger.info(
                            f"持仓中，当前价格: {okx_price}, 开仓均价: {position['okx_entry_price']}, "
                            f"浮动盈亏: {change_pct:.4%}, 方向{position['okx_direction']}, ")

                        # 5分钟k,10%止盈
                        if change_pct >= WIN_LIMIT_5k and k_rate <= 5:
                            logger.info(f"触发止盈条件，准备平仓")
                            close_flag = True

                if "long" == position.get("okx_direction"):
                    if (short_signal_2 or short_signal_1 or short_signal_3 or short_signal_4 or short_signal_5
                            or macd_signal_target["zero_down"] or macd_signal_target["death_cross"]):
                        close_flag = True
                elif "short" == position.get("okx_direction"):
                    if long_signal_2 or long_signal_1 or long_signal_3 or long_signal_4 or long_signal_5 \
                            or macd_signal_target["zero_up"] or macd_signal_target["golden_cross"]:
                        close_flag = True

                if close_flag:
                    close_okx_position_by_order_id(symbol=position["okx_symbol"],
                                                   order_id=position["okx_order_id"],
                                                   okx_qty=position["okx_qty"],
                                                   trade_api=trade_api)
                    position = None
                    logger.info("平仓完成，等待下一次开仓信号")
                    okx_trade_macd_logger.info("平仓macd_signal: " + str(macd_signal_target))
                    okx_trade_macd_logger.info(f"long_signal_2: {long_signal_2}, long_signal_1: {long_signal_1}, "
                                               f"long_signal_3: {long_signal_3}, long_signal_4: {long_signal_4}, "
                                               f"long_signal_5: {long_signal_5}, short_signal_2: {short_signal_2}, "
                                               f"short_signal_1: {short_signal_1}, short_signal_3: {short_signal_3}, "
                                               f"short_signal_4: {short_signal_4}, short_signal_5: {short_signal_5}")
                else:
                    logger.info("持仓中，等待下一次平仓信号 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            logger.error(f"异常: {e}")

        time.sleep(OKX_OPEN_INTERVAL_SEC)


if __name__ == "__main__":
    threads = []
    for SYMBOL in TREND_SYMBOL_LIST:
        t1 = threading.Thread(target=monitor_position_macd,
                              args=(SYMBOL, okx_account_api_test, okx_trade_api_test, okx_market_api, 5),
                              name=f"Thread-{SYMBOL}-Test-5m")
        # t = threading.Thread(target=monitor_position_macd,
        #                      args=(SYMBOL, okx_account_api, okx_trade_api, okx_market_api),
        #                      name=f"Thread-{SYMBOL}")
        t1.start()
        t2 = threading.Thread(target=monitor_position_macd,
                              args=(SYMBOL, okx_account_api_test, okx_trade_api_test, okx_market_api, 15),
                              name=f"Thread-{SYMBOL}-Test-15m")
        t2.start()
        t3 = threading.Thread(target=monitor_position_macd,
                              args=(SYMBOL, okx_account_api_test, okx_trade_api_test, okx_market_api, 1),
                              name=f"Thread-{SYMBOL}-Test-1m")
        t3.start()
        time.sleep(200)
        threads.append(t1)
        threads.append(t2)
    for t in threads:
        t.join()
    # monitor_position_macd(direction_symbol=SYMBOL)
