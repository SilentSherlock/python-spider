import time

from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from enums.RequestEnums import OrderType

from arbitrage_bot.backpack_okx_arbitrage_bot import get_backpack_funding_rate, calculate_funding_rate_diff, \
    execute_backpack_order, close_backpack_position_by_order_id
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
    symbol_sol = "SOL_USDC"
    symbol_sol_perp = "SOL_USDC_PERP"
    ticker = public.get_ticker("SOL_USDC")
    print(f"SOL_USDC Ticker: {ticker.get('lastPrice')}")
    # 获取资金费率
    funding_rate = get_backpack_funding_rate(public, "SOL_USDC_PERP")
    # 资金费率排序测试
    # calculate_funding_rate_diff()
    SOL_USDC_PERP_ticker = public.get_ticker("SOL_USDC_PERP")
    print(f"SOL_USDC_PERP Ticker:{SOL_USDC_PERP_ticker.get('lastPrice')}")
    bid_price_perp = round(float(SOL_USDC_PERP_ticker.get("lastPrice")) * 0.8, 2)
    order_result = execute_backpack_order(
        symbol=symbol_sol_perp,
        side="long",
        qty="1",
        price=str(bid_price_perp),
        order_type=OrderType.LIMIT
    )
    order_id = order_result.get("id")
    order_symbol = order_result.get("symbol")
    time.sleep(5)  # 等待5s后取消订单
    cancel_result = close_backpack_position_by_order_id(order_symbol, order_id)


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

