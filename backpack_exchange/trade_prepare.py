import os


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
