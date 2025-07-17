import numpy as np
import time
import math
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient

from arbitrage_bot.backpack_okx_arbitrage_bot import close_backpack_position_by_order_id
from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys_trade_cat_funding

# 启用代理与加载密钥
proxy_on()
public_key, secret_key = load_backpack_api_keys_trade_cat_funding()
client = AuthenticationClient(public_key, secret_key)
public = PublicClient()

SYMBOL = "ETH_USDC_PERP"
TREND_SYMBOL_LIST = [
    "BTC_USDC_PERP",
    "ETH_USDC_PERP",
    "SOL_USDC_PERP",
    "SUI_USDC_PERP",
    "XRP_USDC_PERP",
]

OPEN_INTERVAL_SEC = 5 * 60  # 每5分钟执行一次
MARGIN = 50  # 保证金
LEVERAGE = 15
LOSS_LIMIT = -0.10  # 亏损10%止损
PROFIT_LIMIT = 0.3  # 盈利30%止盈
PROFIT_DRAWBACK = 0.1  # 盈利回撤10%止盈保护
PROFIT_TRIGGER = 0.075  # 初始止盈目标：7.5%


def monitor_position_with_ema_exit(backpack_price, direction, order_id, backpack_qty, leverage=LEVERAGE,
                                   monitor_symbol=SYMBOL):

    price_history = []
    max_pnl = 0
    trigger_reached = False  # 是否达到初始止盈目标
    monitor_interval = 50  # 监控间隔时间（秒）

    while True:
        time.sleep(monitor_interval)
        current_price = float(public.get_ticker(monitor_symbol)['lastPrice'])
        price_history.append(current_price)
        if len(price_history) > 60:
            price_history.pop(0)

        # 当前盈亏（含杠杆）
        pnl = ((current_price - backpack_price) / backpack_price * leverage) if direction == 'long' \
            else ((backpack_price - current_price) / backpack_price * leverage)

        max_pnl = max(max_pnl, pnl)
        draw_down = max_pnl - pnl

        print(
            f"[监控] 当前价格: {current_price:.4f}, 开仓价: {backpack_price:.4f}, direction: {direction}, 杠杆盈亏: {pnl:.4%}, "
            f"最大盈利: {max_pnl:.4%}, 当前回撤: {draw_down:.4%}")

        # 固定止损逻辑
        if pnl <= LOSS_LIMIT:
            print(f"[止损触发] 盈亏: {pnl:.2%}，亏损达到限制")
            break

        # 初始止盈达到，开始移动止损机制
        if not trigger_reached and pnl >= PROFIT_TRIGGER:
            print(f"[止盈目标触发] 盈利达到{PROFIT_TRIGGER:.2%}，启动折半止盈策略")
            trigger_reached = True

        if trigger_reached:
            if max_pnl >= 0.04:
                stop_draw_down = math.ceil((max_pnl / 2) * 100) / 100  # 向上取整至两位小数
                if draw_down >= stop_draw_down:
                    print(f"[折半止盈] 盈利回撤达到 {draw_down:.2%} >= {stop_draw_down:.2%}，触发平仓")
                    break

        # EMA 死叉判断平仓
        if len(price_history) >= 21:
            ema9 = np.mean(price_history[-9:])
            ema21 = np.mean(price_history[-21:])
            print(f"[EMA] EMA9: {ema9:.4f}, EMA21: {ema21:.4f}")

            if direction == 'long' and ema9 < ema21:
                print("[EMA死叉] 多头仓位出现死叉信号，强制平仓")
                break
            elif direction == 'short' and ema9 > ema21:
                print("[EMA金叉] 空头仓位出现金叉信号，强制平仓")
                break
        # 达到最大止盈线，平仓
        if pnl >= PROFIT_LIMIT:
            print(f"[止盈触发] 盈利达到 {PROFIT_LIMIT:.2%}，触发平仓")
            break

    # 平仓执行
    profit = float(backpack_qty) * (current_price - backpack_price) if direction == 'long' \
        else float(backpack_qty) * (backpack_price - current_price)
    print(f"[平仓] 当前价格: {current_price:.4f}, 盈亏金额: {profit:.4f} USDC")
    close_backpack_position_by_order_id(monitor_symbol, order_id, backpack_qty)


if __name__ == '__main__':
    from backpack_exchange.trend_trade_strategy_bot import run_backpack_strategy, ma_volume_strategy
    run_backpack_strategy(run_symbol=SYMBOL,
                          direction_detector=ma_volume_strategy,
                          direction_detector_args=(SYMBOL,)
                          )
