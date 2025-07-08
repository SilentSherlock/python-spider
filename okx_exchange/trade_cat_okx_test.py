from okx import Funding, Trade, PublicData
import okx.Account as Account

from arbitrage_bot.backpack_okx_arbitrage_bot import get_okx_funding_rate
from backpack_exchange.trade_prepare import proxy_on, load_okx_api_keys, load_okx_api_keys_test

proxy_on()  # 启用代理（如果需要）
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys()
OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST = load_okx_api_keys_test()

okx_live_trading = "0"
okx_test_trading = "1"

okx_account_api = Account.AccountAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

okx_account_api_test = Account.AccountAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                          okx_test_trading)
okx_trade_api_test = Trade.TradeAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False, okx_test_trading)
okx_public_api_test = PublicData.PublicAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                           okx_test_trading)

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

# 获取资金费率及结算时间
funding_rate_result = get_okx_funding_rate(okx_public_api_test, "SOL-USDT-SWAP")
print(f"Funding Rate Result: {funding_rate_result}")
