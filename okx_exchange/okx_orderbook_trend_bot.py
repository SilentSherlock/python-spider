import asyncio
import json
import time
from collections import deque

import numpy as np
from okx.websocket.WsPublicAsync import WsPublicAsync

from utils.logging_setup import setup_logger

# OKX WebSocket 地址
WS_URL = "wss://wspap.okx.com:8443/ws/v5/public"

# 参数配置
DEPTH_LEVEL = 5  # 前 5 档盘口
WINDOW = 30  # 计算 TFI 的窗口大小（秒）
VOLUME_SPIKE_FACTOR = 2  # 成交量放大倍数阈值
ORDER_LIFETIME = 1.0  # 挂单最短存活时间 (秒)，小于此值视为假单

# 缓存
trades_buffer = deque(maxlen=1000)
orderbook_snapshot = {}
last_order_seen = {}  # {price: last_seen_timestamp}

# 日志打印
logger = setup_logger("okx_strategy_trend")


async def okx_strategy(symbol="BTC-USDT-SWAP", k_rate=5):
    ws = WsPublicAsync(url=WS_URL)
    await ws.start()
    book_channel = ""
    trades_channel = ""
    if k_rate == 5:
        book_channel = "books5"
        trades_channel = "trades"

    # 订阅订单簿和成交流
    args = [
        {"channel": book_channel, "instId": symbol},  # 订单簿 top5
        {"channel": trades_channel, "instId": symbol}  # 成交流
    ]

    def ws_message_callback(msg):
        logger.info(f"✅ Subscribed to {symbol} orderbook & trades")
        data = msg

        if "arg" not in data:
            logger.info(f"Received non-arg message: {data}")
            return

        channel = data["arg"]["channel"]

        if channel == book_channel and "data" in data:
            process_orderbook(data["data"][0])

        elif channel == trades_channel and "data" in data:
            for trade in data["data"]:
                process_trade(trade)

        # 每 5 秒计算一次信号
        if int(time.time()) % 5 == 0:
            signal = generate_signal()
            if signal:
                logger.info(f"🚨 Signal: {signal} at {time.strftime('%X')}")

    await ws.subscribe(params=args, callback=ws_message_callback)
    while True:
        await asyncio.sleep(1)


def process_orderbook(orderbook):
    global orderbook_snapshot
    ts = time.time()
    # 四个参数 深度价格-此价格处的数量/合约张数-已废弃字段-此价格的订单数量
    bids = [(float(p), float(sz)) for p, sz, _, _ in orderbook["bids"][:DEPTH_LEVEL]]
    asks = [(float(p), float(sz)) for p, sz, _, _ in orderbook["asks"][:DEPTH_LEVEL]]

    # 过滤掉寿命过短的挂单
    def filter_orders(orders):
        filtered = []
        for p, sz in orders:
            if sz > 0:
                if p not in last_order_seen:
                    last_order_seen[p] = ts
                elif ts - last_order_seen[p] < ORDER_LIFETIME:
                    sz = 0
            else:
                last_order_seen.pop(p, None)
            filtered.append((p, sz))
        return filtered

    orderbook_snapshot = {"bids": filter_orders(bids), "asks": filter_orders(asks)}


def process_trade(trade):
    """缓存成交流数据"""
    trades_buffer.append({
        "side": trade["side"],  # buy / sell
        "sz": float(trade["sz"]),
        "ts": int(trade["ts"])
    })


def generate_signal():
    if not orderbook_snapshot or not trades_buffer:
        return None

    # 1) OBI 订单簿不平衡
    bid_vol = sum(sz for _, sz in orderbook_snapshot["bids"])
    ask_vol = sum(sz for _, sz in orderbook_snapshot["asks"])
    obi = (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)

    # 2) TFI 成交流不平衡（最近 WINDOW 秒）
    now = int(time.time() * 1000)
    recent_trades = [t for t in trades_buffer if now - t["ts"] <= WINDOW * 1000]
    buy_vol = sum(t["sz"] for t in recent_trades if t["side"] == "buy")
    sell_vol = sum(t["sz"] for t in recent_trades if t["side"] == "sell")
    tfi = (buy_vol - sell_vol) / (buy_vol + sell_vol + 1e-9)

    # 3) 成交量放大确认
    vols = [t["sz"] for t in trades_buffer]
    if len(vols) < 20:
        return None
    avg_vol = np.mean(vols[-20:])
    latest_vol = vols[-1]
    volume_spike = latest_vol > VOLUME_SPIKE_FACTOR * avg_vol

    # 4) 组合判断
    if obi > 0.2 and tfi > 0.2 and volume_spike:
        return "LONG ✅"
    elif obi < -0.2 and tfi < -0.2 and volume_spike:
        return "SHORT ✅"
    else:
        return None


if __name__ == "__main__":
    asyncio.run(okx_strategy("BTC-USDT-SWAP"))
