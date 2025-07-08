from okx import Funding
import okx.Account as Account

from backpack_exchange.trade_prepare import proxy_on, load_okx_api_keys

proxy_on()
api_key, secret_key, passphrase = load_okx_api_keys()

# flag = 0 for live trading, 1 for testnet
flag = "0"  # live trading: 0, demo trading: 1
accountAPI = Account.AccountAPI(api_key, secret_key, passphrase, False, flag)
result = accountAPI.get_account_balance()
print(result)
