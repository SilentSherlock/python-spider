import logging
import logging.handlers
import os

# 创建日志目录
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


# okx开立交易macd指标文件路径
okx_trade_macd_file = os.path.join(LOG_DIR, "okx_trade_macd.log")


def setup_logger(name: str = "app"):
    """
    创建并返回一个logger
    :param name: 日志器名称（建议传入模块名：__name__）
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # 设置日志级别

    # 如果已经有 handler，避免重复添加
    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(threadName)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 文件输出（按日期切分，每天一个文件，保留7天）
    # 运行日志文件路径


    log_file = os.path.join(LOG_DIR, name + ".log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=300*1024*1024, backupCount=7, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # 添加到logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def setup_okx_macd_logger():
    """
    创建并返回一个专门用于记录okx macd指标的logger
    """
    logger = logging.getLogger("okx_macd")
    logger.setLevel(logging.DEBUG)

    # 如果已经有 handler，避免重复添加
    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(threadName)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 文件输出（按日期切分，每天一个文件，保留30天）
    file_handler = logging.handlers.TimedRotatingFileHandler(
        okx_trade_macd_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # 添加到logger
    logger.addHandler(file_handler)

    return logger
