import pandas as pd


# -----------------------------
# 1) 基础：EMA / MACD 计算
# -----------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def kline_to_dataframe(kline_data):
    """
    将二维数组的K线数据转换为DataFrame
    kline_data: [
        [timestamp, open, high, low, close, status], ...]
    """
    # kline数据为由新到旧，进行翻转
    kline_data.reverse()
    df = pd.DataFrame(kline_data, columns=["timestamp", "open", "high", "low", "close", "status"])

    # 转换数据类型
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")  # 毫秒时间戳转日期
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    df["status"] = df["status"].astype(int)
    # df = df.iloc[::-1].reset_index(drop=True)
    return df


def calc_macd(kline_data, fast=12, slow=26, signal=9, price_col='close') -> pd.DataFrame:
    df = kline_to_dataframe(kline_data)
    ema_fast = ema(df[price_col], fast)
    ema_slow = ema(df[price_col], slow)
    dif = ema_fast - ema_slow  # 快线
    dea = ema(dif, signal)  # 慢线
    hist = (dif - dea) * 2
    df['DIF'], df['DEA'], df['MACD_HIST'] = dif, dea, hist
    # print(f"MACD计算完成：{len(df)}条数据，DIF:{dif} EMA, DEA:{dea} EMA, MACD:{hist} EMA")
    return df


# -----------------------------
# 2) 交叉类信号 红跌绿涨
# -----------------------------
def crosses(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    prev_dif, prev_dea = d['DIF'].shift(1), d['DEA'].shift(1)
    prev_hist = d['MACD_HIST'].shift(1)

    # 金叉/死叉
    d['golden_cross'] = (prev_dif < prev_dea) & (d['DIF'] > d['DEA'])
    d['death_cross'] = (prev_dif > prev_dea) & (d['DIF'] < d['DEA'])

    # 0轴突破（用 DIF 判定，也可用 MACD_HIST）
    d['zero_up'] = (prev_hist <= 0) & (d['MACD_HIST'] > 0)
    d['zero_down'] = (prev_hist >= 0) & (d['MACD_HIST'] < 0)

    # 柱状图颜色切换（绿->红 / 红->绿）
    d['hist_red_to_green'] = (prev_hist <= 0) & (d['MACD_HIST'] > 0)
    d['hist_green_to_red'] = (prev_hist >= 0) & (d['MACD_HIST'] < 0)
    return d


# -----------------------------
# 3) 二次交叉（确认信号）
#    逻辑：在滚动窗口内出现两次同向交叉，且第2次交叉后的 |HIST| 峰值高于第1次
# -----------------------------
def double_cross(df: pd.DataFrame, lookback=80, peak_window=6) -> pd.DataFrame:
    d = df.copy()
    d['double_golden'] = False
    d['double_death'] = False

    # 交叉点索引
    gold_idx = d.index[d['golden_cross']].to_list()
    death_idx = d.index[d['death_cross']].to_list()

    def mark_double(cross_list, col_name):
        for i in range(1, len(cross_list)):
            t2, t1 = cross_list[i], cross_list[i - 1]
            if (t2 - t1) <= lookback:
                # 比较两次交叉后不久的动能峰值
                h1 = d.loc[t1: t1 + peak_window, 'MACD_HIST'].abs().max()
                h2 = d.loc[t2: t2 + peak_window, 'MACD_HIST'].abs().max()
                if h2 > h1:
                    d.loc[t2, col_name] = True

    # 兼容整数索引/DatetimeIndex：转成位置索引操作更稳健
    d = d.reset_index(drop=False)
    # 交叉点换成位置索引
    gpos = d.index[d['golden_cross']].to_list()
    dpos = d.index[d['death_cross']].to_list()
    mark_double(gpos, 'double_golden')
    mark_double(dpos, 'double_death')
    return d.set_index(d.columns[0], drop=True)


# -----------------------------
# 4) 背离（枢轴点法）
#    底背离：价格 LL，而 MACD_HIST/DIF HL
#    顶背离：价格 HH，而 MACD_HIST/DIF LH
# -----------------------------
def _pivots(series: pd.Series, win=3, mode='low'):
    """
    简易枢轴点：某点为左右win窗口的极小/极大值
    返回布尔序列
    """
    if mode == 'low':
        return (series.rolling(win * 2 + 1, center=True).apply(lambda x: x[win] == x.min(), raw=True) == 1)
    else:
        return (series.rolling(win * 2 + 1, center=True).apply(lambda x: x[win] == x.max(), raw=True) == 1)


def divergences(df: pd.DataFrame, price_col='close', pivot_win=3, use='MACD_HIST') -> pd.DataFrame:
    d = df.copy()
    m = d[use]

    # 枢轴点
    d['pivot_low_p'] = _pivots(d[price_col], win=pivot_win, mode='low')
    d['pivot_high_p'] = _pivots(d[price_col], win=pivot_win, mode='high')
    d['pivot_low_m'] = _pivots(m, win=pivot_win, mode='low')
    d['pivot_high_m'] = _pivots(m, win=pivot_win, mode='high')

    d['bullish_div'] = False
    d['bearish_div'] = False

    # 取最近两个价格低点 / 高点 与 指标低点 / 高点 比较
    lows_p = d.index[d['pivot_low_p']].to_list()
    lows_m = d.index[d['pivot_low_m']].to_list()
    highs_p = d.index[d['pivot_high_p']].to_list()
    highs_m = d.index[d['pivot_high_m']].to_list()

    def last_two(vals):
        return vals[-2:] if len(vals) >= 2 else []

    lp = last_two(lows_p)
    lm = last_two(lows_m)
    hp = last_two(highs_p)
    hm = last_two(highs_m)

    # 底背离：价格新低（lp[1]处价格 < lp[0]），而指标未新低（lm[1]处指标 > lm[0]）
    if len(lp) == 2 and len(lm) == 2:
        if d.loc[lp[1], price_col] < d.loc[lp[0], price_col] and d.loc[lm[1], use] > d.loc[lm[0], use]:
            d.loc[lp[1], 'bullish_div'] = True

    # 顶背离：价格新高，而指标未新高
    if len(hp) == 2 and len(hm) == 2:
        if d.loc[hp[1], price_col] > d.loc[hp[0], price_col] and d.loc[hm[1], use] < d.loc[hm[0], use]:
            d.loc[hp[1], 'bearish_div'] = True

    return d


# -----------------------------
# 5) 双线粘合 & 柱状图放大/缩短
# -----------------------------
def consolidation_and_momentum(df: pd.DataFrame, span=20, tight_pct=0.15, momentum_len=4) -> pd.DataFrame:
    """
    双线粘合：|DIF-DEA| 的分位阈值判定，低于 tight_pct 分位视为粘合（震荡）
    柱状图动能：最近N根绝对值连续放大/缩短
    """
    d = df.copy()
    spread = (d['DIF'] - d['DEA']).abs()
    # 用滚动分位数阈值刻画“很小的分叉”
    q = spread.rolling(span).quantile(tight_pct)
    d['lines_converge'] = spread <= q

    # 动能判断：最近 N 根柱状图绝对值是否单调递增/递减
    abs_hist = d['MACD_HIST'].abs()
    inc = abs_hist.diff(1) > 0
    dec = abs_hist.diff(1) < 0
    d['hist_expanding'] = inc.rolling(momentum_len).sum() == momentum_len  # 连续放大
    d['hist_contracting'] = dec.rolling(momentum_len).sum() == momentum_len  # 连续缩短
    return d

# 计算ema交叉
def ema_cross(df: pd.DataFrame, price_col='close', fast=5, slow=10) -> pd.DataFrame:
    """
    判断EMA5和EMA10是否交叉，生成'ema_golden_cross'和'ema_death_cross'信号
    """
    d = df.copy()
    d['EMA_FAST'] = ema(d[price_col], fast)
    d['EMA_SLOW'] = ema(d[price_col], slow)
    prev_fast = d['EMA_FAST'].shift(1)
    prev_slow = d['EMA_SLOW'].shift(1)
    d['ema_golden_cross'] = (prev_fast < prev_slow) & (d['EMA_FAST'] > d['EMA_SLOW'])
    d['ema_death_cross'] = (prev_fast > prev_slow) & (d['EMA_FAST'] < d['EMA_SLOW'])
    return d

# -----------------------------
# 6) 一键生成所有信号
# -----------------------------
def macd_signals(kline_data, price_col='close',
                 fast=12, slow=26, signal=9,
                 pivot_win=3, use_for_div='MACD_HIST',
                 lookback_double=80, peak_window=6,
                 span_converge=20, tight_pct=0.15, momentum_len=3):
    d = calc_macd(kline_data, fast, slow, signal, price_col)
    d = crosses(d)
    d = double_cross(d, lookback=lookback_double, peak_window=peak_window)
    d = ema_cross(d)
    d = divergences(d, price_col=price_col, pivot_win=pivot_win, use=use_for_div)
    d = consolidation_and_momentum(d, span=span_converge, tight_pct=tight_pct, momentum_len=momentum_len)
    return d


# -----------------------------
# 7) 用法示例
# -----------------------------
# 假设你已有 df，至少包含列：['close']（可选再带 'high','low','open','volume'）
# df.index 为时间戳更佳。
# df = # 生成50组模拟K线数据

# 你可以像下面这样筛选开仓点：
#
# 多头开仓条件例：
# long_entry = df['golden_cross'] & (df['DIF'] < 0)  # 低位金叉
#
# 或者强势趋势启动例：
# long_entry = df['zero_up'] & df['hist_expanding'] & (~df['lines_converge'])
#
# 反转抄底例（更激进）：
# long_entry = df['bullish_div'] & df['hist_green_to_red']  # 柱子翻红+底背离
#
# 空头同理：
# short_entry = df['death_cross'] & (df['DIF'] > 0)         # 高位死叉
# short_entry = df['zero_down'] & df['hist_expanding']
# short_entry = df['bearish_div'] & df['hist_red_to_green']

if __name__ == '__main__':
    import random
    import time


    def generate_kline_data(num=50):
        kline_data = []
        ts = int(time.time() * 1000)
        price = 3.7
        for i in range(num):
            open_p = round(price + random.uniform(-0.05, 0.05), 3)
            high_p = round(open_p + random.uniform(0, 0.1), 3)
            low_p = round(open_p - random.uniform(0, 0.1), 3)
            close_p = round(low_p + random.uniform(0, high_p - low_p), 3)
            status = random.randint(0, 1)
            kline_data.append([
                str(ts + i * 60000),  # 每根K线间隔1分钟
                str(open_p),
                str(high_p),
                str(low_p),
                str(close_p),
                str(status)
            ])
            price = close_p
        return kline_data


    kline_data = generate_kline_data(50)
    df = macd_signals(kline_data)

    # 多头开仓条件
    long_entry = df['golden_cross'] & (df['DIF'] < 0)
    # 空头开仓条件
    short_entry = df['death_cross'] & (df['DIF'] > 0)

    print("macd_signals结果：")
    print(df)

    print("\n多头信号行：")
    print(df[long_entry][['timestamp', 'close', 'DIF', 'DEA', 'MACD_HIST']])

    print("\n空头信号行：")
    print(df[short_entry][['timestamp', 'close', 'DIF', 'DEA', 'MACD_HIST']])
