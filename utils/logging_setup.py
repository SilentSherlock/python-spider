import logging
import logging.handlers
import os

# 创建日志目录
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件路径
LOG_FILE = os.path.join(LOG_DIR, "app.log")


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
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # 添加到logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
