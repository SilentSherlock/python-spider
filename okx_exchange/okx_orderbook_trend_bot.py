import asyncio
import aiohttp
import websockets
import json
import time
from collections import deque, defaultdict
from statistics import mean

# ========== 参数配置 ==========
SYMBOL = "ETH-USDT-SWAP"  # OKX 合约符号，如 BTC-USDT-SWAP / ETH-USDT-SWAP
DEPTH_LIMIT = 5  # OKX books5, books50_l2_tbt（支持 5 / 50）
TOP_N = 10  # OBI 前 N 档
TFI_WINDOW_SEC = 3  # TFI 窗口（秒）
MID_SMA_LEN = 10  # 中价短均线
OBI_LONG_TH = 0.20
OBI_SHORT_TH = -0.20
TFI_LONG_TH = 0.60
TFI_SHORT_TH = 0.40
MIN_SIGNAL_INTERVAL = 2.0
PRINT_EVERY = 1.0

# ========== OKX 端点 ==========
REST_DEPTH = "https://www.okx.com/api/v5/market/books"
WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"


# ========== 订单簿 ==========
class OrderBook:
    def __init__(self):
        self.bids = defaultdict(float)
        self.asks = defaultdict(float)
        self.ready = False

    def load_snapshot(self, snapshot):
        self.bids.clear()
        self.asks.clear()
        for p, s, *_ in snapshot["bids"]:
            self.bids[float(p)] = float(s)
        for p, s, *_ in snapshot["asks"]:
            self.asks[float(p)] = float(s)
        self.ready = True

    def apply_delta(self, delta):
        for p, s, *_ in delta["bids"]:
            p, s = float(p), float(s)
            if s == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = s
        for p, s, *_ in delta["asks"]:
            p, s = float(p), float(s)
            if s == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = s
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
    def __init__(self, window_sec=3):
        self.window_sec = window_sec
        self.buffer = deque()

    def add(self, ts_ms, is_aggressive_buy):
        now = ts_ms / 1000.0
        self.buffer.append((now, 1 if is_aggressive_buy else 0))
        cutoff = now - self.window_sec
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    def tfi(self):
        if not self.buffer:
            return 0.5
        buys = sum(x for _, x in self.buffer)
        return buys / len(self.buffer)


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
        if last_mid is None:
            return "no-signal"
        if (obi > OBI_LONG_TH) and (tfi > TFI_LONG_TH) and self.mid_above_ma(last_mid):
            if not self.throttled():
                return "long"
        elif (obi < OBI_SHORT_TH) and (tfi < TFI_SHORT_TH) and self.mid_below_ma(last_mid):
            if not self.throttled():
                return "short"
        return "no-signal"


# ========== 工具 ==========
async def fetch_snapshot(session, symbol, depth="5"):
    params = {"instId": symbol, "sz": depth}
    async with session.get(REST_DEPTH, params=params, timeout=10) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["data"][0]


# ========== 主流程 ==========
async def run(symbol=SYMBOL):
    ob = OrderBook()
    tf = TradeFlow(window_sec=TFI_WINDOW_SEC)
    se = SignalEngine()

    async with aiohttp.ClientSession() as session:
        snapshot = await fetch_snapshot(session, symbol, str(DEPTH_LIMIT))
        ob.load_snapshot(snapshot)

    async with websockets.connect(WS_PUBLIC, ping_interval=20, ping_timeout=20) as ws:
        sub_msg = {
            "op": "subscribe",
            "args": [
                {"channel": f"books{DEPTH_LIMIT}", "instId": symbol},
                {"channel": "trades", "instId": symbol}
            ]
        }
        await ws.send(json.dumps(sub_msg))

        last_print = 0.0
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if "arg" not in data:
                continue

            channel = data["arg"]["channel"]
            if channel.startswith("books"):
                for update in data.get("data", []):
                    ob.apply_delta(update)
                    mid = ob.mid_price()
                    se.update_mid(mid)

            elif channel == "trades":
                for t in data.get("data", []):
                    ts = int(t["ts"])
                    side = t["side"]  # "buy"/"sell"
                    is_aggr_buy = (side == "buy")
                    tf.add(ts, is_aggr_buy)

            now = time.time()
            if now - last_print >= PRINT_EVERY:
                last_print = now
                obi = ob.top_n_imbalance(TOP_N)
                tfi = tf.tfi()
                mid = ob.mid_price()
                bb, ba = ob.best_bid(), ob.best_ask()

                signal = se.decide(obi, tfi, mid)
                print(
                    f"[{symbol}] bb={bb:.2f} ba={ba:.2f} mid={mid:.2f} "
                    f"OBI({TOP_N})={obi:+.3f} TFI({TFI_WINDOW_SEC}s)={tfi:.2f} "
                    f"signal={signal}"
                )


if __name__ == "__main__":
    """
    运行：
        pip install aiohttp websockets
        python okx_orderflow.py
    """
    asyncio.run(run(SYMBOL))
