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
# 配置参数区
# -----------------------------
WS_URL = "wss://wspap.okx.com:8443/ws/v5/public"

DEPTH_LEVEL = 10  # 盘口深度
WINDOW = 60  # 统计窗口（秒）
VOLUME_SPIKE_FACTOR = 2.0  # 成交量突增因子
ORDER_LIFETIME_MS = 5000  # 订单生存时间（毫秒）
MIN_VOL_SAMPLES = 40  # 最小成交样本数
OFI_WINDOW_MS = 3000  # OFI指标窗口（毫秒）

EMA1_SEC = 60  # EMA1周期（秒）
EMA2_SEC = 300  # EMA2周期（秒）
RECALC_THROTTLE_MS = 200  # 计算节流（毫秒）

VOL_LOW_BPS = 8  # 低波动阈值
VOL_HIGH_BPS = 35  # 高波动阈值
DEPTH_MIN = 5_000  # 最小盘口深度
EDGE_BPS = 2  # 最小套利边际

ENTER_LONG = 82  # 做多入场分数
EXIT_LONG = 68  # 做多离场分数
ENTER_SHORT = 18  # 做空入场分数
EXIT_SHORT = 32  # 做空离场分数
COOLDOWN_MS = 1500  # 信号冷却时间（毫秒）

logger = setup_logger("okx_orderbook_trend")
signal_logger = setup_logger("okx_orderbook_trend_signals")


def now_ms():
    """返回当前时间戳（毫秒）"""
    return int(time.time() * 1000)


class SymbolContext:
    """
    单合约上下文，维护盘口、成交、指标等状态
    """

    def __init__(self, symbol):
        self.symbol = symbol
        self.trades_buffer = deque(maxlen=20000)  # 成交缓存
        self.mid_buffer = deque(maxlen=EMA2_SEC * 10)  # 中间价缓存
        self.orderbook_snapshot = None  # 当前盘口快照
        self.prev_orderbook_snapshot = None  # 上一盘口快照
        self.last_order_seen = {}  # 记录订单出现时间

        # 盘口增减量缓存
        self.ask_added = deque(maxlen=20000)
        self.ask_removed = deque(maxlen=20000)
        self.bid_added = deque(maxlen=20000)
        self.bid_removed = deque(maxlen=20000)
        self.signals = deque(maxlen=1200)  # 信号记录

        # 指标相关
        self.ema1 = None
        self.ema2 = None
        self.vwap_num = 0.0
        self.vwap_den = 0.0
        self.last_calc_ms = 0
        self.last_signal_ms = 0
        self.position_bias = 0  # 当前持仓方向

    def update_mid_and_trend(self):
        """更新中间价和EMA趋势"""
        if not self.orderbook_snapshot: return
        bids = self.orderbook_snapshot["bids"]
        asks = self.orderbook_snapshot["asks"]
        if not bids or not asks: return
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0
        self.mid_buffer.append((now_ms(), mid))

        def ema_update(prev, x, alpha):
            return x if prev is None else (alpha * x + (1 - alpha) * prev)

        alpha1 = 2 / (EMA1_SEC + 1)
        alpha2 = 2 / (EMA2_SEC + 1)
        self.ema1 = ema_update(self.ema1, mid, alpha1)
        self.ema2 = ema_update(self.ema2, mid, alpha2)

    def update_vwap_on_trade(self, trade):
        """成交时更新VWAP分子分母"""
        price = float(trade["px"])
        size = float(trade["sz"])
        self.vwap_num += price * size
        self.vwap_den += size

    def get_vwap(self):
        """返回当前VWAP"""
        return (self.vwap_num / self.vwap_den) if self.vwap_den > 0 else None

    def get_volatility_bps(self, lookback_ms=60_000):
        """计算波动率（基点）"""
        cutoff = now_ms() - lookback_ms
        arr = [p for ts, p in self.mid_buffer if ts >= cutoff]
        if len(arr) < 10:
            return VOL_LOW_BPS
        mu = np.mean(arr)
        sd = np.std(arr)
        return 0 if mu == 0 else (sd / mu) * 10_000

    def process_orderbook_delta(self, data0):
        """
        处理盘口增量数据，更新盘口快照和增减量缓存
        """
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
                        sz *= 0.3
                else:
                    self.last_order_seen.pop(p, None)
                out.append((p, sz))
            return out

        filtered_bids = filter_orders(bids)
        filtered_asks = filter_orders(asks)

        prev_b_dict = {p: s for p, s in self.prev_orderbook_snapshot["bids"]} if self.prev_orderbook_snapshot else {}
        prev_a_dict = {p: s for p, s in self.prev_orderbook_snapshot["asks"]} if self.prev_orderbook_snapshot else {}
        new_b_dict = {p: s for p, s in filtered_bids}
        new_a_dict = {p: s for p, s in filtered_asks}

        def level_weights(side_prices):
            if not side_prices: return {}
            weights = {}
            for i, (p, _) in enumerate(side_prices):
                w = 0.9 ** i
                weights[p] = w
            return weights

        wb = level_weights(filtered_bids)
        wa = level_weights(filtered_asks)

        # 记录盘口增减量
        for p in set(new_b_dict) | set(prev_b_dict):
            d = new_b_dict.get(p, 0.0) - prev_b_dict.get(p, 0.0)
            if d > 0:
                self.bid_added.append((ts, d * wb.get(p, 0.2)))
            elif d < 0:
                self.bid_removed.append((ts, -d * wb.get(p, 0.2)))

        for p in set(new_a_dict) | set(prev_a_dict):
            d = new_a_dict.get(p, 0.0) - prev_a_dict.get(p, 0.0)
            if d > 0:
                self.ask_added.append((ts, d * wa.get(p, 0.2)))
            elif d < 0:
                self.ask_removed.append((ts, -d * wa.get(p, 0.2)))

        self.prev_orderbook_snapshot = copy.deepcopy(self.orderbook_snapshot) if self.orderbook_snapshot else None
        self.orderbook_snapshot = {"bids": filtered_bids, "asks": filtered_asks}

        self.update_mid_and_trend()

    def process_trade_entry(self, trade):
        """处理成交数据，更新成交缓存和VWAP"""
        ts = int(trade["ts"])
        price = float(trade["px"])
        size = float(trade["sz"])
        side = trade["side"]
        self.trades_buffer.append((ts, price, size, side))
        self.update_vwap_on_trade(trade)

    # -------------------------
    # 各类指标计算
    # -------------------------
    def compute_obi(self):
        """订单簿不平衡指标"""
        bid_vol = sum(sz for _, sz in self.orderbook_snapshot["bids"])
        ask_vol = sum(sz for _, sz in self.orderbook_snapshot["asks"])
        return (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)

    def compute_tfi(self):
        """成交流入指标"""
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
        """订单流指标"""
        cutoff = now_ms() - OFI_WINDOW_MS
        bid_add = sum(sz for ts, sz in self.bid_added if ts >= cutoff)
        bid_rem = sum(sz for ts, sz in self.bid_removed if ts >= cutoff)
        ask_add = sum(sz for ts, sz in self.ask_added if ts >= cutoff)
        ask_rem = sum(sz for ts, sz in self.ask_removed if ts >= cutoff)
        net = (bid_add - bid_rem) - (ask_add - ask_rem)
        total_change = (bid_add + bid_rem + ask_add + ask_rem) + 1e-9
        cancel_ratio = (bid_rem + ask_rem) / total_change
        if cancel_ratio > 0.75:
            net *= 0.5
        return net

    def compute_refill_ratio(self):
        """盘口补单比率"""
        cutoff = now_ms() - WINDOW * 1000
        ask_add = sum(sz for ts, sz in self.ask_added if ts >= cutoff)
        ask_rem = sum(sz for ts, sz in self.ask_removed if ts >= cutoff)
        bid_add = sum(sz for ts, sz in self.bid_added if ts >= cutoff)
        bid_rem = sum(sz for ts, sz in self.bid_removed if ts >= cutoff)
        refill_ask = ask_add / (ask_rem + 1e-9)
        refill_bid = bid_add / (bid_rem + 1e-9)
        return refill_bid, refill_ask

    def compute_uptick_ratio(self):
        """成交价上行比率"""
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
        """检测大单扫单"""
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
        """检测成交量突增"""
        vols = [sz for _, _, sz, _ in self.trades_buffer]
        if len(vols) < 20:
            return 0.0
        avg_vol = np.mean(vols[-20:])
        latest_vol = vols[-1]
        return latest_vol / (avg_vol + 1e-9)

    def get_depth_stats(self):
        """盘口加权深度统计"""
        if not self.orderbook_snapshot: return 0.0, 0.0, 0.0
        wb = sum(sz * (0.9 ** i) for i, (_, sz) in enumerate(self.orderbook_snapshot["bids"]))
        wa = sum(sz * (0.9 ** i) for i, (_, sz) in enumerate(self.orderbook_snapshot["asks"]))
        total = wb + wa
        return wb, wa, total

    def get_dynamic_weights(self):
        """根据波动率和深度动态调整各因子权重"""
        vol_bps = self.get_volatility_bps()
        _, _, depth_total = self.get_depth_stats()
        if vol_bps <= VOL_LOW_BPS:
            w_trend = 0.35
            w_book = 0.5
            w_trade = 0.15
        elif vol_bps >= VOL_HIGH_BPS:
            w_trend = 0.45
            w_book = 0.25
            w_trade = 0.30
        else:
            w_trend = 0.4
            w_book = 0.4
            w_trade = 0.2
        if depth_total < DEPTH_MIN:
            w_book *= 0.7
            s = w_trend + w_book + w_trade
            w_trend, w_book, w_trade = w_trend / s, w_book / s, w_trade / s
        return w_trend, w_book, w_trade

    def trend_gate(self):
        """趋势门控，判断EMA趋势和VWAP偏离"""
        if self.ema1 is None or self.ema2 is None:
            return 0
        slope = 1 if self.ema1 > self.ema2 else (-1 if self.ema1 < self.ema2 else 0)
        vwap = self.get_vwap()
        if vwap:
            last_mid = self.mid_buffer[-1][1] if self.mid_buffer else None
            if last_mid:
                dev = (last_mid - vwap) / vwap
                if slope > 0 and dev > 0.01:
                    slope = max(0, slope)
                if slope < 0 and dev < -0.01:
                    slope = min(0, slope)
        return slope

    def compute_scores(self):
        """
        综合计算各类指标，输出最终信号分数
        """
        if not self.orderbook_snapshot or len(self.trades_buffer) < MIN_VOL_SAMPLES:
            return None
        wb, wa, depth = self.get_depth_stats()
        if depth < DEPTH_MIN:
            return {"final": 50, "note": "shallow_depth"}
        tfi = self.compute_tfi()
        uptick = 2 * (self.compute_uptick_ratio() - 0.5)
        sweep = self.detect_sweep()
        trend_score = np.clip(np.mean([tfi, uptick, sweep]), -1, 1)
        obi = self.compute_obi()
        ofi_raw = self.compute_ofi()
        ofi = np.tanh(ofi_raw / max(depth, 1.0))
        refill_bid, refill_ask = self.compute_refill_ratio()
        refill_score = np.tanh(refill_bid - refill_ask)
        orderbook_score = np.clip(np.mean([obi, ofi, refill_score]), -1, 1)
        vol_spike = self.detect_volume_spike()
        trade_score = np.tanh(vol_spike - VOLUME_SPIKE_FACTOR)
        w_trend, w_book, w_trade = self.get_dynamic_weights()
        final_raw = w_trend * trend_score + w_book * orderbook_score + w_trade * trade_score
        gate = self.trend_gate()
        est_edge_bps = abs(final_raw) * max(self.get_volatility_bps(), 1)
        if gate == 0 or est_edge_bps < EDGE_BPS:
            final_raw *= 0.3
        final_score = int((np.clip(final_raw, -1, 1) + 1) * 50)
        self.signals.append({
            "timestamp": now_ms(),
            "obi": float(obi),
            "tfi": float(tfi),
            "uptick": float(uptick),
            "sweep": int(sweep),
            "ofi": float(ofi),
            "refill_bid": float(refill_bid),
            "refill_ask": float(refill_ask),
            "vol_spike": float(vol_spike),
            "ema1": float(self.ema1) if self.ema1 else None,
            "ema2": float(self.ema2) if self.ema2 else None,
            "gate": int(gate),
            "depth": float(depth),
            "est_edge_bps": float(est_edge_bps),
        })
        logger.info(f"[{self.symbol}] Trend({trend_score:.3f}) Book({orderbook_score:.3f}) "
                    f"Trade({trade_score:.3f}) | Gate:{gate} Vol:{self.get_volatility_bps():.1f}bps "
                    f"Depth:{depth:.1f} | Edge:{est_edge_bps:.2f}bps Final:{final_score}")
        signal_logger.info(
            f"[{self.symbol}] Trend({trend_score:.3f}) Book({orderbook_score:.3f}) "
            f"Trade({trade_score:.3f}) | Gate:{gate} Vol:{self.get_volatility_bps():.1f}bps "
            f"Depth:{depth:.1f} | Edge:{est_edge_bps:.2f}bps Final:{final_score}"
        )
        return {
            "trend": round(trend_score, 3),
            "orderbook": round(orderbook_score, 3),
            "trade": round(trade_score, 3),
            "final": final_score,
            "gate": gate,
            "depth": depth,
            "edge_bps": round(est_edge_bps, 2),
        }


# -----------------------------
# 主逻辑
# -----------------------------
async def run_symbol(ws, symbol):
    """
    单合约主循环，订阅盘口和成交，实时计算信号
    """
    ctx = SymbolContext(symbol)

    def callback0(raw):
        """WebSocket回调，处理盘口和成交推送"""
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if "arg" not in msg: return
        ch = msg["arg"].get("channel", "")
        if ch.startswith("books") and "data" in msg:
            ctx.process_orderbook_delta(msg["data"][0])
        elif ch == "trades" and "data" in msg:
            for t in msg["data"]:
                ctx.process_trade_entry(t)

    args = [
        {"channel": "books10", "instId": symbol},
        {"channel": "trades", "instId": symbol}
    ]
    await ws.subscribe(args, callback=callback0)
    while True:
        now = now_ms()
        # 节流计算信号
        if now - ctx.last_calc_ms >= RECALC_THROTTLE_MS:
            scores = ctx.compute_scores()
            ctx.last_calc_ms = now
            if scores:
                f = scores["final"]
                gate = scores["gate"]
                action = "HOLD"
                # 多空信号判定与持仓切换
                if ctx.position_bias >= 0 and gate >= 0:
                    if f >= ENTER_LONG and (now - ctx.last_signal_ms) >= COOLDOWN_MS:
                        if ctx.position_bias <= 0:
                            action = "ENTER_LONG"
                            ctx.position_bias = +1
                            ctx.last_signal_ms = now
                    elif f <= EXIT_LONG and ctx.position_bias == +1:
                        action = "EXIT_LONG"
                        ctx.position_bias = 0
                        ctx.last_signal_ms = now
                if ctx.position_bias <= 0 and gate <= 0:
                    if f <= ENTER_SHORT and (now - ctx.last_signal_ms) >= COOLDOWN_MS:
                        if ctx.position_bias >= 0:
                            action = "ENTER_SHORT"
                            ctx.position_bias = -1
                            ctx.last_signal_ms = now
                    elif f >= EXIT_SHORT and ctx.position_bias == -1:
                        action = "EXIT_SHORT"
                        ctx.position_bias = 0
                        ctx.last_signal_ms = now

                if action != "HOLD":
                    signal_logger.info(
                        f"[{symbol}] {action} | score={f} gate={gate} "
                        f"edge={scores['edge_bps']}bps depth={int(scores['depth'])}"
                    )
        await asyncio.sleep(0.02)


async def main():
    """
    启动所有合约的信号计算任务
    """
    tasks = []
    for sym in TREND_SYMBOL_LIST:
        ws = WsPublicAsync(url=WS_URL)
        await ws.start()
        tasks.append(asyncio.create_task(run_symbol(ws, sym)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    # 程序入口
    asyncio.run(main())
