import os


def proxy_on():
    """
    This function is a placeholder for enabling a proxy.
    """
    # 在代码中设置全局代理
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:10809'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:10809'


# 从本地文件读取backpack API Key 和 Secret
def load_backpack_api_keys(path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\backpack\\TradeCat.txt"):
    with open(path, "r") as f:
        lines = f.read().splitlines()
    api_key = lines[0].strip()
    secret_key = lines[1].strip()
    return api_key, secret_key


# 从给定路径读取okx api key等参数
def load_okx_api_keys(path="C:\\Users\\15361\\OneDrive\\文档\\finance\\api\\okx\\TradeCat-OKX.txt"):
    with open(path, "r") as f:
        lines = f.read().splitlines()
    api_key = lines[0].strip()
    secret_key = lines[1].strip()
    passphrase = lines[2].strip() if len(lines) > 2 else ""
    return api_key, secret_key, passphrase
