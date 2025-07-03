import sol_volume_brush
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from backpack_exchange.trade_prepare import proxy_on, load_api_keys

proxy_on()

api_key, secret_key = load_api_keys()
client = AuthenticationClient(public_key=api_key, secret_key=secret_key)
public = PublicClient()

print(client.get_balances())
