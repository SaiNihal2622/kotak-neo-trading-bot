"""Loguru setup for the bot."""
import sys
from pathlib import Path
from loguru import logger


def setup_logger(level: str = "INFO", log_file: str = "logs/bot.log") -> "logger":
    """Configure loguru with console + rotating file sink."""
    logger.remove()
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <7}</level> | "
        "<cyan>{name}:{function}:{line}</cyan> | "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, level=level, format=fmt, colorize=True)
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_path),
        level=level,
        format=fmt,
        rotation="20 MB",
        retention="14 days",
        compression="zip",
    )
    return logger
