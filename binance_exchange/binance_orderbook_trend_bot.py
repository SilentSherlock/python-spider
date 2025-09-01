import asyncio
import aiohttp
import websockets
import json
import time
from collections import deque, defaultdict
from statistics import mean

# ========== 可调参数 ==========
SYMBOL = "ETHUSDT"  # 币对（Binance U 合约写大写，例如 BTCUSDT / ETHUSDT / SOLUSDT）
DEPTH_LIMIT = 100  # REST 快照深度（5/10/20/50/100）
TOP_N = 10  # 计算 OBI 的前 N 档
TFI_WINDOW_SEC = 3  # 计算 TFI 的时间窗口（秒）
MID_SMA_LEN = 10  # 中价短均线长度（tick 数）
OBI_LONG_TH = 0.20  # 多头 OBI 阈值
OBI_SHORT_TH = -0.20  # 空头 OBI 阈值
TFI_LONG_TH = 0.60  # 多头 TFI 阈值（>0.5 偏多）
TFI_SHORT_TH = 0.40  # 空头 TFI 阈值（<0.5 偏空）
MIN_SIGNAL_INTERVAL = 2.0  # 两次信号最小间隔（秒）去抖
PRINT_EVERY = 1.0  # 控制台打印间隔（秒）

# ========== 端点（Binance U 永续） ==========
REST_DEPTH = "https://fapi.binance.com/fapi/v1/depth"
WS_STREAM = "wss://fstream.binance.com/stream?streams={streams}"
# depth 增量（100ms）： {symbol}@depth@100ms
# 逐笔成交：             {symbol}@trade
DEPTH_STREAM = f"{SYMBOL.lower()}@depth@100ms"
TRADE_STREAM = f"{SYMBOL.lower()}@trade"


# ========== 订单簿数据结构 ==========
class OrderBook:
    """
    维护一个可增量更新的订单簿（Binance depth stream）
    - bids/asks: dict[price] = size
    - 使用 last_update_id + u/U/pu 来确保顺序正确（按官方建议）
    """

    def __init__(self):
        self.bids = defaultdict(float)  # price -> size
        self.asks = defaultdict(float)
        self.last_update_id = None
        self.ready = False

    def load_snapshot(self, snapshot):
        self.bids.clear()
        self.asks.clear()
        for p, s in snapshot["bids"]:
            self.bids[float(p)] = float(s)
        for p, s in snapshot["asks"]:
            self.asks[float(p)] = float(s)
        self.last_update_id = snapshot["lastUpdateId"]
        self.ready = True

    def _apply_side(self, side_dict, updates):
        for p_str, s_str in updates:
            p = float(p_str)
            s = float(s_str)
            if s == 0.0:
                side_dict.pop(p, None)
            else:
                side_dict[p] = s

    def apply_delta(self, delta):
        """
        delta: {'e':'depthUpdate','E':..., 's':..., 'U': firstUpdateId, 'u': finalUpdateId, 'pu': prevFinalUpdateId, 'b': bids, 'a': asks}
        需要确保与 REST snapshot 对齐（pu == last_update_id）
        """
        if not self.ready:
            return False

        U = delta.get("U")
        u = delta.get("u")
        pu = delta.get("pu")

        # 首包校验：pu 必须等于我们本地的 last_update_id
        if self.last_update_id is None:
            return False
        if pu is not None and pu != self.last_update_id:
            # 序列不同步，需要重新拉 snapshot
            return False

        # 应用增量
        self._apply_side(self.bids, delta["b"])
        self._apply_side(self.asks, delta["a"])
        self.last_update_id = u
        return True

    def top_n_imbalance(self, n=10):
        if not self.bids or not self.asks:
            return 0.0

        top_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:n]
        top_asks = sorted(self.asks.items(), key=lambda x: x[0])[:n]
        bid_vol = sum(s for _, s in top_bids)
        ask_vol = sum(s for _, s in top_asks)
        total = bid_vol + ask_vol
        if total <= 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    def best_bid(self):
        return max(self.bids.keys()) if self.bids else None

    def best_ask(self):
        return min(self.asks.keys()) if self.asks else None

    def mid_price(self):
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is None or ba is None:
            return None
        return 0.5 * (bb + ba)


# ========== 成交流（TFI） ==========
class TradeFlow:
    """
    维护最近 TFI_WINDOW_SEC 的成交记录，计算主动买/卖比例
    - Binance 逐笔成交字段 m: isBuyerMaker
      m == True  => 买方是做市商 => 主动方是卖方（主动卖）
      m == False => 主动方是买方（主动买）
    """

    def __init__(self, window_sec=3):
        self.window_sec = window_sec
        self.buffer = deque()  # (ts, is_aggr_buy)

    def add(self, ts_ms, is_aggressive_buy):
        now = ts_ms / 1000.0
        self.buffer.append((now, 1 if is_aggressive_buy else 0))
        # 清理过期
        cutoff = now - self.window_sec
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    def tfi(self):
        """
        返回窗口内主动买比例（0~1）
        """
        if not self.buffer:
            return 0.5
        buys = sum(x for _, x in self.buffer)
        return buys / len(self.buffer)


# ========== 工具 ==========
async def fetch_snapshot(session, symbol, limit=100):
    params = {"symbol": symbol, "limit": limit}
    async with session.get(REST_DEPTH, params=params, timeout=10) as resp:
        resp.raise_for_status()
        return await resp.json()


# ========== 信号器 ==========
class SignalEngine:
    def __init__(self):
        self.mid_ma = deque(maxlen=MID_SMA_LEN)
        self.last_signal_ts = 0.0

    def update_mid(self, mid):
        if mid is not None:
            self.mid_ma.append(mid)

    def mid_above_ma(self, last_mid):
        if len(self.mid_ma) < self.mid_ma.maxlen:
            return False
        return last_mid > mean(self.mid_ma)

    def mid_below_ma(self, last_mid):
        if len(self.mid_ma) < self.mid_ma.maxlen:
            return False
        return last_mid < mean(self.mid_ma)

    def throttled(self):
        now = time.time()
        if now - self.last_signal_ts < MIN_SIGNAL_INTERVAL:
            return True
        self.last_signal_ts = now
        return False

    def decide(self, obi, tfi, last_mid):
        """
        返回 "long" / "short" / "no-signal"
        核心逻辑：OBI + TFI 同向，并结合价格相对中价短均线的位置
        """
        if last_mid is None:
            return "no-signal"

        # 去抖：太频繁就跳过
        # （这里在返回前再判断，避免打印时被抑制）
        if (obi > OBI_LONG_TH) and (tfi > TFI_LONG_TH) and self.mid_above_ma(last_mid):
            if not self.throttled():
                return "long"
        elif (obi < OBI_SHORT_TH) and (tfi < TFI_SHORT_TH) and self.mid_below_ma(last_mid):
            if not self.throttled():
                return "short"
        return "no-signal"


# ========== 主流程 ==========
async def run(symbol=SYMBOL):
    ob = OrderBook()
    tf = TradeFlow(window_sec=TFI_WINDOW_SEC)
    se = SignalEngine()

    streams = f"{DEPTH_STREAM}/{TRADE_STREAM}"
    ws_url = WS_STREAM.format(streams=streams)

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                # 1) 先拉一次快照
                snapshot = await fetch_snapshot(session, symbol, DEPTH_LIMIT)
                ob.load_snapshot(snapshot)

                # 2) 打开 WS，接收增量
                async with websockets.connect(ws_url, max_queue=None, ping_interval=20, ping_timeout=20) as ws:
                    last_print = 0.0
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        stream = data.get("stream", "")
                        payload = data.get("data", {})

                        # depth 增量
                        if stream.endswith("@depth@100ms"):
                            # 注意：Binance depthUpdate 里是 'U','u','pu','b','a'
                            ok = ob.apply_delta({
                                "U": payload.get("U"),
                                "u": payload.get("u"),
                                "pu": payload.get("pu"),
                                "b": payload.get("b", []),
                                "a": payload.get("a", []),
                            })
                            if not ok:
                                # 序列失配，重拉快照
                                snapshot = await fetch_snapshot(session, symbol, DEPTH_LIMIT)
                                ob.load_snapshot(snapshot)
                                continue

                            mid = ob.mid_price()
                            se.update_mid(mid)

                        # trade 逐笔
                        elif stream.endswith("@trade"):
                            # m == True: isBuyerMaker => 主动方是卖方
                            is_aggr_buy = not payload.get("m", True)
                            tf.add(payload.get("T"), is_aggr_buy)

                        # 定期打印 & 产生信号
                        now = time.time()
                        if now - last_print >= PRINT_EVERY:
                            last_print = now
                            obi = ob.top_n_imbalance(TOP_N)
                            tfi = tf.tfi()
                            mid = ob.mid_price()
                            bb, ba = ob.best_bid(), ob.best_ask()

                            signal = se.decide(obi, tfi, mid)
                            print(
                                f"[{symbol}] "
                                f"bb={bb:.2f} ba={ba:.2f} mid={mid:.2f}  "
                                f"OBI({TOP_N})={obi:+.3f}  TFI({TFI_WINDOW_SEC}s)={tfi:.2f}  "
                                f"signal={signal}"
                            )
                            # TODO: 在这里对接下单逻辑（风控：滑点、最小成交量、冷却时间等）

        except Exception as e:
            print("WS/HTTP error:", e, "— 5s 后重试")
            await asyncio.sleep(5.0)


if __name__ == "__main__":
    """
    直接运行：
        pip install aiohttp websockets
        python orderflow_signal.py
    说明：
      - 如果要接 OKX：
         * REST 快照 -> OKX /api/v5/market/books?instId=ETH-USDT-SWAP&sz=...
         * WS 频道     -> public books/books5 + public trades
         * 字段名不同（u/U/pu 机制不同），需要按 OKX 规格调整 apply_delta 逻辑
      - 实盘下单前请务必加：风控（最大下单量、滑点限制、冷却时间、仓位管理、限价委托等）
    """
    asyncio.run(run(SYMBOL))
