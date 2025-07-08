from enums.RequestEnums import OrderType, OrderSide, TimeInForce

import sol_volume_brush
from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from backpack_exchange.trade_prepare import proxy_on, load_backpack_api_keys

proxy_on()

api_key, secret_key = load_backpack_api_keys()
client = AuthenticationClient(public_key=api_key, secret_key=secret_key)
public = PublicClient()

if __name__ == '__main__':
    # 打印当前账户余额
    balance = client.get_balances()
    print(f"Current Balances: {balance}")
    # 获取SOL标的当前标记价格
    ticker = public.get_ticker("SOL_USDC")
    print(f"SOL_USDC Ticker: {ticker.get('lastPrice')}")
    # bid_price = round(float(ticker.get("lastPrice")) * 0.75, 2)
    # ask_price = round(float(ticker.get("lastPrice")) * 1.25, 2)
    # print(f"Bid Price: {bid_price}, Ask Price: {ask_price}")
    # order = client.execute_order(
    #     orderType=OrderType.LIMIT,
    #     side=OrderSide.BID,
    #     symbol="SOL_USDC",
    #     price=str(bid_price),
    #     quantity="0.1",  # Replace with desired quantity
    #     timeInForce=TimeInForce.GTC,
    #     postOnly=True
    # )
    # print(f"Order placed: {order}")
    # order = client.execute_order(
    #     orderType=OrderType.LIMIT,
    #     side=OrderSide.ASK,
    #     symbol="SOL_USDC",
    #     price=str(ask_price),
    #     quantity="0.1",
    #     timeInForce=TimeInForce.GTC,
    #     postOnly=True
    # )
    # print(f"Order placed: {order}")

