import asyncio
import json
import time
import copy
from collections import deque

import numpy as np
from okx.websocket.WsPublicAsync import WsPublicAsync

from okx_exchange.okx_trend_trade_strategy_bot import TREND_SYMBOL_LIST
from utils.logging_setup import setup_logger

# -----------------------------
# 配置
# -----------------------------
WS_URL = "wss://wspap.okx.com:8443/ws/v5/public"

DEPTH_LEVEL = 5  # 订单深度
WINDOW = 60  # 成交流计算窗口（秒）
VOLUME_SPIKE_FACTOR = 2.0
ORDER_LIFETIME_MS = 3000  # 订单最小存活时间，防止频繁撤单
MIN_VOL_SAMPLES = 20
OFI_WINDOW_MS = 5000

logger = setup_logger("okx_strategy_trend")
signal_logger = setup_logger("okx_strategy_trend_signals")


def now_ms():
    return int(time.time() * 1000)


class SymbolContext:
    def __init__(self, symbol):
        self.symbol = symbol
        self.trades_buffer = deque(maxlen=10000)
        self.orderbook_snapshot = None
        self.prev_orderbook_snapshot = None
        self.last_order_seen = {}

        self.ask_added = deque(maxlen=10000)
        self.ask_removed = deque(maxlen=10000)
        self.bid_added = deque(maxlen=10000)
        self.bid_removed = deque(maxlen=10000)

    # -------------------------
    # 数据处理
    # -------------------------
    def process_orderbook_delta(self, data0):
        ts = now_ms()
        bids_raw = data0["bids"][:DEPTH_LEVEL]
        asks_raw = data0["asks"][:DEPTH_LEVEL]

        bids = [(float(p), float(sz)) for p, sz, *_ in bids_raw]
        asks = [(float(p), float(sz)) for p, sz, *_ in asks_raw]

        def filter_orders(orders):
            out = []
            for p, sz in orders:
                if sz > 0:
                    if p not in self.last_order_seen:
                        self.last_order_seen[p] = ts
                    elif ts - self.last_order_seen[p] < ORDER_LIFETIME_MS:
                        sz = 0.0
                else:
                    self.last_order_seen.pop(p, None)
                out.append((p, sz))
            return out

        filtered_bids = filter_orders(bids)
        filtered_asks = filter_orders(asks)

        # 增量更新
        new_b_dict = {p: s for p, s in filtered_bids}
        new_a_dict = {p: s for p, s in filtered_asks}
        prev_b_dict = {p: s for p, s in self.prev_orderbook_snapshot["bids"]} if self.prev_orderbook_snapshot else {}
        prev_a_dict = {p: s for p, s in self.prev_orderbook_snapshot["asks"]} if self.prev_orderbook_snapshot else {}

        for p in set(new_b_dict) | set(prev_b_dict):
            d = new_b_dict.get(p, 0.0) - prev_b_dict.get(p, 0.0)
            if d > 0:
                self.bid_added.append((ts, d))
            elif d < 0:
                self.bid_removed.append((ts, -d))

        for p in set(new_a_dict) | set(prev_a_dict):
            d = new_a_dict.get(p, 0.0) - prev_a_dict.get(p, 0.0)
            if d > 0:
                self.ask_added.append((ts, d))
            elif d < 0:
                self.ask_removed.append((ts, -d))

        self.prev_orderbook_snapshot = copy.deepcopy(self.orderbook_snapshot) if self.orderbook_snapshot else None
        self.orderbook_snapshot = {"bids": filtered_bids, "asks": filtered_asks}

    def process_trade_entry(self, trade):
        ts = int(trade["ts"])
        price = float(trade["px"])
        size = float(trade["sz"])
        side = trade["side"]
        self.trades_buffer.append((ts, price, size, side))

    # -------------------------
    # 指标计算
    # -------------------------
    def compute_obi(self):
        bid_vol = sum(sz for _, sz in self.orderbook_snapshot["bids"])
        ask_vol = sum(sz for _, sz in self.orderbook_snapshot["asks"])
        return (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)

    def compute_tfi(self):
        cutoff = now_ms() - WINDOW * 1000
        buys = sells = 0.0
        for ts, _, size, side in reversed(self.trades_buffer):
            if ts < cutoff:
                break
            if side == "buy":
                buys += size
            else:
                sells += size
        total = buys + sells
        return (buys - sells) / total if total else 0.0

    def compute_ofi(self):
        cutoff = now_ms() - OFI_WINDOW_MS
        bid_add = sum(sz for ts, sz in self.bid_added if ts >= cutoff)
        bid_rem = sum(sz for ts, sz in self.bid_removed if ts >= cutoff)
        ask_add = sum(sz for ts, sz in self.ask_added if ts >= cutoff)
        ask_rem = sum(sz for ts, sz in self.ask_removed if ts >= cutoff)
        return (bid_add - bid_rem) - (ask_add - ask_rem)

    def compute_refill_ratio(self):
        cutoff = now_ms() - WINDOW * 1000
        ask_add = sum(sz for ts, sz in self.ask_added if ts >= cutoff)
        ask_rem = sum(sz for ts, sz in self.ask_removed if ts >= cutoff)
        bid_add = sum(sz for ts, sz in self.bid_added if ts >= cutoff)
        bid_rem = sum(sz for ts, sz in self.bid_removed if ts >= cutoff)
        refill_ask = ask_add / (ask_rem + 1e-9)
        refill_bid = bid_add / (bid_rem + 1e-9)
        return refill_bid, refill_ask

    def compute_uptick_ratio(self):
        cutoff = now_ms() - WINDOW * 1000
        upticks = downticks = 0
        trades = [t for t in self.trades_buffer if t[0] >= cutoff]
        for i in range(1, len(trades)):
            _, p0, _, _ = trades[i - 1]
            _, p1, _, side = trades[i]
            if side == "buy" and p1 > p0:
                upticks += 1
            elif side == "sell" and p1 < p0:
                downticks += 1
        total = upticks + downticks
        return upticks / total if total else 0.5

    def detect_sweep(self):
        if not self.trades_buffer or not self.orderbook_snapshot:
            return 0
        _, _, size, side = self.trades_buffer[-1]
        total_bid = sum(sz for _, sz in self.orderbook_snapshot["bids"])
        total_ask = sum(sz for _, sz in self.orderbook_snapshot["asks"])
        if size > 0.5 * total_bid and side == "sell":
            return -1
        if size > 0.5 * total_ask and side == "buy":
            return 1
        return 0

    def detect_volume_spike(self):
        vols = [sz for _, _, sz, _ in self.trades_buffer]
        if len(vols) < 20:
            return 0.0
        avg_vol = np.mean(vols[-20:])
        latest_vol = vols[-1]
        return latest_vol / (avg_vol + 1e-9)

    # -------------------------
    # 分层打分
    # -------------------------
    def compute_scores(self):
        if not self.orderbook_snapshot or len(self.trades_buffer) < MIN_VOL_SAMPLES:
            return None

        # 趋势分
        tfi = self.compute_tfi()
        uptick = 2 * (self.compute_uptick_ratio() - 0.5)
        sweep = self.detect_sweep()
        trend_score = np.mean([tfi, uptick, sweep])

        # 盘口分
        obi = self.compute_obi()
        ofi = np.tanh(self.compute_ofi() / 1000.0)
        refill_bid, refill_ask = self.compute_refill_ratio()
        refill_score = np.tanh(refill_bid - refill_ask)
        orderbook_score = np.mean([obi, ofi, refill_score])

        # 成交分
        vol_spike = self.detect_volume_spike()
        trade_score = np.tanh(vol_spike - VOLUME_SPIKE_FACTOR)

        # 综合分
        final = 0.4 * trend_score + 0.4 * orderbook_score + 0.2 * trade_score
        final_score = int((final + 1) * 50)  # [-1,1] -> [0,100]
        logger.info(f"[{self.symbol}] "
                    f"OBI: {obi:.3f}, TFI: {tfi:.3f}, Uptick: {uptick:.3f}, Sweep: {sweep}, OFI: {ofi:.3f}, "
                    f"Refill: ({refill_bid:.3f},{refill_ask:.3f}), VolSpike: {vol_spike:.3f} | "
                    f"Trend: {trend_score:.3f}, Orderbook: {orderbook_score:.3f}, Trade: {trade_score:.3f}, Final: {final_score}")

        return {
            "trend": round(trend_score, 3),
            "orderbook": round(orderbook_score, 3),
            "trade": round(trade_score, 3),
            "final": final_score
        }


# -----------------------------
# 主逻辑
# -----------------------------
async def run_symbol(ws, symbol):
    ctx = SymbolContext(symbol)

    def callback0(msg):
        if "arg" not in msg:
            return
        msg = json.loads(msg)
        ch = msg["arg"].get("channel", "")
        if ch.startswith("books") and "data" in msg:
            ctx.process_orderbook_delta(msg["data"][0])
        elif ch == "trades" and "data" in msg:
            for t in msg["data"]:
                ctx.process_trade_entry(t)

    args = [
        {"channel": "books5", "instId": symbol},
        {"channel": "trades", "instId": symbol}
    ]
    await ws.subscribe(args, callback=callback0)

    while True:
        scores = ctx.compute_scores()
        if scores:
            if scores["final"] > 60:
                signal_logger.info(f"[{symbol}] 🚀 LONG bias | {scores}")
            elif scores["final"] < 40:
                signal_logger.info(f"[{symbol}] 🔻 SHORT bias | {scores}")
            else:
                signal_logger.info(f"[{symbol}] 😐 Neutral | {scores}")
        await asyncio.sleep(1)


async def main():
    tasks = []
    for sym in TREND_SYMBOL_LIST:
        ws = WsPublicAsync(url=WS_URL)
        await ws.start()
        tasks.append(asyncio.create_task(run_symbol(ws, sym)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
