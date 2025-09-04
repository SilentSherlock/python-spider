import os

from backpack_exchange_sdk.authenticated import AuthenticationClient
from backpack_exchange_sdk.public import PublicClient
from okx import Account, Trade, Funding, PublicData, MarketData


def proxy_on():
    """
    This function is a placeholder for enabling a proxy.
    """
    # 在代码中设置全局代理
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:10809'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:10809'


# 读取backpack API Key 和 Secret 两行
def load_backpack_api_keys(path):
    """
    从指定路径读取backpack API Key 和 Secret
    :param path: 文件路径，默认为本地文件路径
    :return: 返回API Key和Secret
    """
    with open(path, "r") as f:
        lines = f.read().splitlines()
    api_key = lines[0].strip()
    secret_key = lines[1].strip()
    return api_key, secret_key


# 读取okx API Key 和 Secret 三行
def load_okx_api_keys(path):
    with open(path, "r") as f:
        lines = f.read().splitlines()
    api_key = lines[0].strip()
    secret_key = lines[1].strip()
    passphrase = lines[2].strip() if len(lines) > 2 else ""
    return api_key, secret_key, passphrase


# 从本地文件读取backpack API Key 和 Secret
def load_backpack_api_keys_trade_cat(path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\backpack\\TradeCat.txt"):
    """
    从默认路径读取backpack API Key 和 Secret
    :param path: 文件路径，默认为本地文件路径
    :return: 返回API Key和Secret
    """
    return load_backpack_api_keys(path)


# 从本地文件读取backpack API Key 和 Secret，资金费率子账户
def load_backpack_api_keys_trade_cat_funding(
        path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\backpack\\TradeCat-Funding.txt"):
    """
    从默认路径读取backpack API Key 和 Secret，资金费率子账户
    :param path: 文件路径，默认为本地文件路径
    :return: 返回API Key和Secret
    """
    return load_backpack_api_keys(path)


# 从本地文件读取backpack API Key 和 Secret，现货刷量子账户
def load_backpack_api_keys_trade_cat_volume(
        path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\backpack\\TradeCat-Volume.txt"):
    """
    从默认路径读取backpack API Key 和 Secret，现货刷量子账户
    :param path: 文件路径，默认为本地文件路径
    :return: 返回API Key和Secret
    """
    return load_backpack_api_keys(path)


# 从本地文件读取backpack API Key 和 Secret，合约自动化子账户
def load_backpack_api_keys_trade_cat_auto(
        path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\backpack\\TradeCat-Auto.txt"):
    return load_backpack_api_keys(path)


# 从给定路径读取okx api key等参数
def load_okx_api_keys_trade_cat_okx(path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\okx\\TradeCat-OKX.txt"):
    return load_okx_api_keys(path)


# 从给定路径读取okx api key等参数，模拟交易
def load_okx_api_keys_trade_cat_okx_test(
        path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\okx\\TradeCat-OKX-Test.txt"):
    return load_okx_api_keys(path)


# 从给定路径读取okx api key等参数，趋势交易
def load_okx_api_keys_trade_cat_okx_trend(
        path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\okx\\TradeCat-OKX-Trend-Strategy.txt"):
    return load_okx_api_keys(path)

# okx api
okx_live_trading = "0"
okx_test_trading = "1"
OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE = load_okx_api_keys_trade_cat_okx_trend()
okx_account_api = Account.AccountAPI(
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_trade_api = Trade.TradeAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_funding_api = Funding.FundingAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_public_api = PublicData.PublicAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)
okx_market_api = MarketData.MarketAPI(OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, False, okx_live_trading)

# okx test api
OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST = load_okx_api_keys_trade_cat_okx_test()
okx_account_api_test = Account.AccountAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                          okx_test_trading)
okx_trade_api_test = Trade.TradeAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False, okx_test_trading)
okx_public_api_test = PublicData.PublicAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                           okx_test_trading)
okx_market_api_test = MarketData.MarketAPI(OKX_API_KEY_TEST, OKX_SECRET_KEY_TEST, OKX_PASSPHRASE_TEST, False,
                                           okx_test_trading)

# backpack trade cat auto api
backpack_public_api = PublicClient()
backpack_trade_cat_auto_api, backpack_trade_cat_auto_secret = load_backpack_api_keys_trade_cat_auto()
backpack_trade_cat_auto_client = AuthenticationClient(backpack_trade_cat_auto_api, backpack_trade_cat_auto_secret)

