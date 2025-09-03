import asyncio
import threading
import time
from collections import deque, defaultdict
import numpy as np

from okx.websocket.WsPublicAsync import WsPublicAsync
from okx_exchange.okx_trend_trade_strategy_bot import TREND_SYMBOL_LIST
from utils.logging_setup import setup_logger

# -----------------------------
# 配置
# -----------------------------
WS_URL = "wss://wspap.okx.com:8443/ws/v5/public"

DEPTH_LEVEL = 5  # 使用前 N 档计算静态 OBI 与做差
WINDOW = 60  # TFI / OFI / Up-tick 窗口 (秒)
VOLUME_SPIKE_FACTOR = 2.0  # 最新成交 > avg(last_n) * factor -> 放量
ORDER_LIFETIME_MS = 3000  # 挂单存活阈值，毫秒，小于视为“闪单”
MIN_VOL_SAMPLES = 20

# 动态因子阈值（经验值，实盘需调参）
TFI_TH = 0.25
OFI_TH = 0.0
REFILL_RATIO_TH = 0.9
UP_TICK_RATE_TH = 0.6
SWEEP_COUNT_TH = 1
VOLUME_SPIKE_REQUIRED = True  # 是否把 volume_spike 作为必须条件

# -----------------------------
# 全局缓存（每个实例共用同一份结构，若多 symbol 并行，可改为 per-symbol 存储）
# -----------------------------
trades_buffer = deque(maxlen=10000)  # 存 (ts_ms, price, size, side)
# orderbook_snapshot: {"bids":[(p,size),...], "asks":[(p,size),...]}
orderbook_snapshot = None
prev_orderbook_snapshot = None

# orderbook delta events for dynamic OFI/refill:
ask_added = deque()  # (ts_ms, qty)
ask_removed = deque()
bid_added = deque()
bid_removed = deque()

# 记录挂单首次见到时间（ms）
last_order_seen = dict()  # price -> first_seen_ts_ms

# 简单日志
logger = setup_logger("okx_strategy_trend")
signal_logger = setup_logger("okx_strategy_trend_signals")


# -----------------------------
# 工具函数
# -----------------------------
def now_ms():
    return int(time.time() * 1000)


def prune_deques(window_sec=WINDOW):
    cutoff = now_ms() - int(window_sec * 1000)
    for q in (ask_added, ask_removed, bid_added, bid_removed):
        while q and q[0][0] < cutoff:
            q.popleft()


def map_levels_to_dict(levels):
    """levels: list of [price, size, ...] -> dict price->size"""
    return {float(p): float(s) for p, s, *rest in levels}


# -----------------------------
# 处理 orderbook：算快照并产生增量事件（新增/减少）
# -----------------------------
def process_orderbook_delta(new_data):
    """
    new_data: data[0] from books5 channel, contains 'bids' and 'asks' arrays
    产生：orderbook_snapshot, prev_orderbook_snapshot, 并把新增/减少量放到相应队列
    """
    global orderbook_snapshot, prev_orderbook_snapshot, last_order_seen
    ts = now_ms()

    # parse up to DEPTH_LEVEL
    bids_raw = new_data["bids"][:DEPTH_LEVEL]
    asks_raw = new_data["asks"][:DEPTH_LEVEL]

    bids = [(float(p), float(sz)) for p, sz, *rest in bids_raw]
    asks = [(float(p), float(sz)) for p, sz, *rest in asks_raw]

    # filter out 'flash' orders using last_order_seen (use ms)
    def filter_and_stamp(side_list):
        out = []
        for p, sz in side_list:
            if sz > 0:
                if p not in last_order_seen:
                    last_order_seen[p] = ts
                elif (ts - last_order_seen[p]) < ORDER_LIFETIME_MS:
                    # still consider it present but mark as tiny to ignore in totals
                    # we'll keep the level but zero its size to neutralize fake order
                    sz = 0.0
            else:
                last_order_seen.pop(p, None)
            out.append((p, sz))
        return out

    filtered_bids = filter_and_stamp(bids)
    filtered_asks = filter_and_stamp(asks)

    # build dicts for delta computation vs prev snapshot
    new_b_dict = {p: s for p, s in filtered_bids}
    new_a_dict = {p: s for p, s in filtered_asks}

    prev_b_dict = {}
    prev_a_dict = {}
    if prev_orderbook_snapshot:
        prev_b_dict = {p: s for p, s in prev_orderbook_snapshot.get("bids", [])}
        prev_a_dict = {p: s for p, s in prev_orderbook_snapshot.get("asks", [])}

    # compute deltas and push events
    # for bids
    for p in set(list(new_b_dict.keys()) + list(prev_b_dict.keys())):
        new_sz = new_b_dict.get(p, 0.0)
        prev_sz = prev_b_dict.get(p, 0.0)
        d = new_sz - prev_sz
        if d > 0:
            bid_added.append((ts, d))
        elif d < 0:
            bid_removed.append((ts, -d))
    # for asks
    for p in set(list(new_a_dict.keys()) + list(prev_a_dict.keys())):
        new_sz = new_a_dict.get(p, 0.0)
        prev_sz = prev_a_dict.get(p, 0.0)
        d = new_sz - prev_sz
        if d > 0:
            ask_added.append((ts, d))
        elif d < 0:
            ask_removed.append((ts, -d))

    # shift snapshots
    prev_orderbook_snapshot = {"bids": filtered_bids, "asks": filtered_asks}
    orderbook_snapshot = {"bids": filtered_bids, "asks": filtered_asks}

    logger.debug(f"Orderbook snapshot updated (ts={ts})")


# -----------------------------
# 处理 trade
# -----------------------------
def process_trade_entry(tr):
    """
    tr: dict with keys 'side','sz','px','ts' from OKX trade event
    we append into trades_buffer as (ts_ms, price, size, side)
    """
    ts = int(tr["ts"])
    price = float(tr["px"])
    size = float(tr["sz"])
    side = tr["side"]  # 'buy' or 'sell'
    trades_buffer.append((ts, price, size, side))


# -----------------------------
# 动态特征计算
# -----------------------------
def compute_tfi(window_sec=WINDOW):
    """TFI = (buy_vol - sell_vol) / (buy_vol + sell_vol) over recent window"""
    cutoff = now_ms() - int(window_sec * 1000)
    buys = sells = 0.0
    count = 0
    for ts, price, size, side in reversed(trades_buffer):
        if ts < cutoff:
            break
        count += 1
        if side == "buy":
            buys += size
        else:
            sells += size
    total = buys + sells
    if total == 0:
        return 0.0
    return (buys - sells) / total


def compute_ofi_and_refill(window_sec=WINDOW):
    """
    OFI := (B_add - B_rm) - (A_add - A_rm) using events in window
    refill_ratio_ask = ask_added / (ask_removed)  (if small -> refill insufficient)
    refill_ratio_bid  = bid_added / (bid_removed)
    """
    prune_deques(window_sec)
    A_add = sum(x[1] for x in ask_added)
    A_rm = sum(x[1] for x in ask_removed)
    B_add = sum(x[1] for x in bid_added)
    B_rm = sum(x[1] for x in bid_removed)

    ofi = (B_add - B_rm) - (A_add - A_rm)
    # normalize OFI by total activity
    total = A_add + A_rm + B_add + B_rm
    ofi_norm = ofi / (total + 1e-9)

    refill_ask = A_add / (A_rm + 1e-9)
    refill_bid = B_add / (B_rm + 1e-9)
    return ofi_norm, refill_ask, refill_bid, A_add, A_rm, B_add, B_rm


def compute_up_tick_rate(window_sec=WINDOW):
    """比例：最近窗口里，price > prev_price 的成交次数 / 总成交次数"""
    cutoff = now_ms() - int(window_sec * 1000)
    prev_price = None
    up = total = 0
    for ts, price, size, side in reversed(trades_buffer):
        if ts < cutoff:
            break
        if prev_price is not None:
            if price > prev_price:
                up += 1
            total += 1
        prev_price = price
    if total == 0:
        return 0.5
    return up / total


def compute_sweep_count(window_sec=WINDOW):
    """
    简单的 sweep_count：统计最近窗口内，买单成交时消耗了超过1个 ask 档位的次数
    使用 prev_orderbook_snapshot as reference for ask levels
    """
    if not prev_orderbook_snapshot:
        return 0
    cutoff = now_ms() - int(window_sec * 1000)
    asks = prev_orderbook_snapshot.get("asks", [])
    asks_sorted = sorted(asks, key=lambda x: x[0])  # ascending price
    sweep = 0
    for ts, price, size, side in reversed(trades_buffer):
        if ts < cutoff:
            break
        if side != "buy":
            continue
        # count cumulative ask qty up to trade price
        cum = 0.0
        levels = 0
        for p, s in asks_sorted:
            if p <= price + 1e-9:
                cum += s
                levels += 1
            else:
                break
        if levels > 1 and size > 0:
            # if trade size consumes more than single level capacity, count as sweep
            # approximate: if size > asks_sorted[0][1] => sweep deeper
            if asks_sorted:
                if size > asks_sorted[0][1] * 1.1:  # consumed more than top-level
                    sweep += 1
    return sweep


def compute_volume_spike():
    vols = [t[2] for t in trades_buffer]
    if len(vols) < MIN_VOL_SAMPLES:
        return False, None, None
    latest = vols[-1]
    avg = float(np.mean(vols[-MIN_VOL_SAMPLES:]))
    return latest > VOLUME_SPIKE_FACTOR * avg, latest, avg


# -----------------------------
# 组合决策：把所有指标汇总并给出信号
# -----------------------------
def generate_signal():
    if not orderbook_snapshot or len(trades_buffer) < MIN_VOL_SAMPLES:
        return None

    obi_bid = sum(sz for _, sz in orderbook_snapshot["bids"])
    obi_ask = sum(sz for _, sz in orderbook_snapshot["asks"])
    obi = (obi_bid - obi_ask) / (obi_bid + obi_ask + 1e-9)

    tfi = compute_tfi(WINDOW)
    ofi_norm, refill_ask, refill_bid, A_add, A_rm, B_add, B_rm = compute_ofi_and_refill(WINDOW)
    up_tick = compute_up_tick_rate(WINDOW)
    sweep = compute_sweep_count(WINDOW)
    vol_spike, latest_vol, avg_vol = compute_volume_spike()

    # log metrics
    logger.info(
        f"OBI: {obi:+.3f}, TFI: {tfi:+.3f}, OFI_norm: {ofi_norm:+.3f}, refill_ask:{refill_ask:.3f}, "
        f"up_tick:{up_tick:.3f}, sweep:{sweep}, latest_vol:{latest_vol}, avg_vol:{avg_vol:.3f}"
    )

    # Decision logic (long)
    long_cond = (
            (tfi > TFI_TH) and
            (ofi_norm > OFI_TH) and
            (refill_ask < REFILL_RATIO_TH) and
            (up_tick > UP_TICK_RATE_TH) and
            (sweep >= SWEEP_COUNT_TH)
    )
    # Decision logic (short) - symmetric
    short_cond = (
            (tfi < -TFI_TH) and
            (ofi_norm < -OFI_TH) and
            (refill_bid < REFILL_RATIO_TH) and
            (up_tick < (1 - UP_TICK_RATE_TH)) and
            (sweep >= SWEEP_COUNT_TH)
    )

    # volume spike required optionally
    if VOLUME_SPIKE_REQUIRED:
        long_cond = long_cond and vol_spike
        short_cond = short_cond and vol_spike

    if long_cond:
        signal_logger.info(
            f"LONG signal. metrics: OBI:{obi:+.3f},TFI:{tfi:+.3f},OFI:{ofi_norm:+.3f}, refill_ask:{refill_ask:.3f}, "
            f"up_tick:{up_tick:.3f}, sweep:{sweep}, vol:{latest_vol}/{avg_vol:.3f}")
        return "LONG"
    if short_cond:
        signal_logger.info(
            f"SHORT signal. metrics: OBI:{obi:+.3f},TFI:{tfi:+.3f},OFI:{ofi_norm:+.3f}, refill_bid:{refill_bid:.3f}, "
            f"up_tick:{up_tick:.3f}, sweep:{sweep}, vol:{latest_vol}/{avg_vol:.3f}")
        return "SHORT"
    return None


# -----------------------------
# WebSocket 消息回调与 主流程
# -----------------------------
async def okx_strategy(strategy_symbol="BTC-USDT-SWAP", k_rate=5):
    global prev_orderbook_snapshot
    ws = WsPublicAsync(url=WS_URL)
    await ws.start()

    book_channel = "books5" if k_rate == 5 else "books50"
    trades_channel = "trades"

    args = [
        {"channel": book_channel, "instId": strategy_symbol},
        {"channel": trades_channel, "instId": strategy_symbol}
    ]

    last_signal_ts = 0

    def ws_message_callback(msg):
        """
        msg is already a dict provided by WsPublicAsync
        handle both subscription ACK / info & data messages
        """
        try:
            # subscription ack/messages may contain 'event' or 'arg' keys
            if "event" in msg:
                logger.debug(f"WS event: {msg}")
                return

            # normal data messages have 'arg' and 'data'
            if "arg" not in msg:
                logger.debug(f"Non-arg msg: {msg}")
                return

            # identify channel
            ch = msg["arg"].get("channel", "")
            # process books update
            if ch.startswith("books") and "data" in msg and msg["data"]:
                data0 = msg["data"][0]
                # shift prev snapshot for sweep calculation
                prev_orderbook_snapshot = orderbook_snapshot.copy() if orderbook_snapshot else None
                process_orderbook_delta(data0)
            # process trades
            if ch == "trades" and "data" in msg:
                for t in msg["data"]:
                    process_trade_entry(t)

            # throttled signal every X seconds
            now_s = int(time.time())
            nonlocal_last = None  # placeholder to emphasize nonlocal usage below
        except Exception as e:
            logger.exception(f"Error in ws_message_callback: {e}")

    # correct subscribe signature
    await ws.subscribe(args, callback=ws_message_callback)

    # main keepalive loop
    while True:
        # compute signal every ~1s but throttle logging/actions
        try:
            now = int(time.time())
            if now - last_signal_ts >= 1:
                last_signal_ts = now
                sig = generate_signal()
                if sig:
                    signal_logger.info(f"Signal {sig} for {strategy_symbol} at {time.strftime('%X')}")
        except Exception:
            logger.exception("Error in periodic signal generation")
        await asyncio.sleep(1)


# -----------------------------
# 多线程启动（每个 symbol 启一个线程运行其 own event loop)
# -----------------------------
if __name__ == "__main__":
    threads = []
    for symbol in TREND_SYMBOL_LIST:
        def runner(sym=symbol):
            asyncio.run(okx_strategy(strategy_symbol=sym, k_rate=5))
        t = threading.Thread(target=runner, name=f"OkxOrderbookTrendBot-{symbol}")
        threads.append(t)
        t.start()
        time.sleep(0.2)

    for t in threads:
        t.join()
