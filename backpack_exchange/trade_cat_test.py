import os

import sol_volume_brush
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient

# 在代码中设置全局代理
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:10809'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:10809'

api_key, secret_key = sol_volume_brush.load_api_keys()
client = AuthenticationClient(public_key=api_key, secret_key=secret_key)
public = PublicClient()

print(client.get_balances())