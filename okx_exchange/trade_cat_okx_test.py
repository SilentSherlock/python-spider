import time

from okx import Funding, Trade, PublicData
import okx.Account as Account

from arbitrage_bot.backpack_okx_arbitrage_bot import get_okx_funding_rate, SYMBOL_MAP
from backpack_exchange.trade_prepare import (proxy_on, load_okx_api_keys_trade_cat_okx,
                                             load_okx_api_keys_trade_cat_okx_test)

proxy_on()  # 启用代理（如果需要）
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys_trade_cat_okx()
OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST = load_okx_api_keys_trade_cat_okx_test()

okx_live_trading = "0"
okx_test_trading = "1"

okx_account_api = Account.AccountAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

okx_account_api_test = Account.AccountAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                          okx_test_trading)
okx_trade_api_test = Trade.TradeAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False, okx_test_trading)
okx_public_api_test = PublicData.PublicAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                           okx_test_trading)

# def close_okx_position_by_order_id(symbol, order_id):
#
#
#     order_info = okx_trade_api_test.get_order(instId=symbol, ordId=order_id)
#     if not order_info or order_info.get("code") != "0":
#         raise Exception(f"查询OKX订单失败: {order_info.get('msg', '未知错误')}")
#     data = order_info["data"][0]
#     pos_side = data.get("posSide", "net")
#     side = data["side"]
#     qty = data["sz"]
#     price = data.get("px", None)
#     ord_type = data.get("ordType", "market")
#     # 反向方向
#     close_side = "buy" if side == "sell" else "sell"
#     print(f"[OKX] 准备平仓: {symbol}, 方向: {close_side}, 数量: {qty}, 价格: {price}, 类型: {ord_type}")
#     # 平仓下单
#     order_result1 = okx_trade_api_test.place_order(
#         instId=symbol,
#         tdMode="isolated",
#         side=close_side,
#         ordType=ord_type,
#         sz=qty,
#         px=price,
#         posSide=pos_side,
#         reduceOnly=True
#     )
#     print(f"[OKX] 平仓结果: {order_result1}")
#     if order_result1.get("code") != "0":
#         raise Exception(f"OKX 平仓失败: {order_result1.get('msg', '未知错误')}")
#     return order_result1

# 获取账户余额
account_balance_result = okx_account_api.get_account_balance()
print(account_balance_result)

# 设置账户模式为合约 test
position_mode_result = okx_account_api_test.set_position_mode(
    posMode="long_short_mode",  # 开平仓模式
)
print(f"Position Mode Result: {position_mode_result}")

# 设置SOL-USDT-SWAP合约交易参数
leverage_result = okx_account_api_test.set_leverage(
    instId="SOL-USDT-SWAP",  # 交易对
    mgnMode="isolated",       # 逐仓模式
    lever="5",                 # 杠杆倍数（根据实际需求调整）
    posSide="short"          # 空头持仓
)
print(f"Leverage Result: {leverage_result}")

# 下合约订单
# order_result = okx_trade_api_test.place_order(
#     instId="SOL-USDT-SWAP",  # 交易对
#     tdMode="isolated",       # 逐仓模式
#     side="sell",             # 做空
#     ordType="market",        # 市价单
#     sz="10",                  # 下单数量（合约张数，根据实际需求调整）
#     posSide="short",         # 空头持仓
#     # margin="1000"            # 保证金（单位：USDT，部分API可能不需要此参数）
# )
# print(f"Order Result: {order_result}")
# time.sleep(5)
# 平仓订单
# order_id = order_result['data'][0].get("ordId")
# close_order_result = close_okx_position_by_order_id("SOL-USDT-SWAP", order_id)

okx_ticker = okx_public_api_test.get_instruments(instType="SWAP", instId="SOL-USDT-SWAP")
# 获取合约交易对的lotsz和minSz
symbol_lotsz_minsz_map = {}
for symbol in SYMBOL_MAP.keys():
    ticker_info = okx_public_api_test.get_instruments(instType="SWAP", instId=symbol)
    print(f"Ticker Info for {symbol}: {ticker_info}")
    if ticker_info and ticker_info.get("code") == "0" and ticker_info.get("data"):
        data = ticker_info["data"][0]
        ctVal = data.get("ctVal")
        lotsz = data.get("lotSz")
        minsz = data.get("minSz")
        symbol_lotsz_minsz_map[symbol] = {"lotsz": lotsz, "minsz": minsz, "ctVal": ctVal}
print(f"Symbol lotsz & minsz map: {symbol_lotsz_minsz_map}")

print(f"Ticker Instruments Result: {okx_ticker}")

# 获取资金费率及结算时间
funding_rate_result = get_okx_funding_rate(okx_public_api_test, "SOL-USDT-SWAP")

print(f"Funding Rate Result: {funding_rate_result}")
