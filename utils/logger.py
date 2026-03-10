"""
Merkezi loglama modülü.

loguru tabanlı logger: hem konsola hem logs/kap.log dosyasına yazar.
Format: {time} | {level} | {module} | {message}
"""

import sys
from pathlib import Path

from loguru import logger

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "kap.log"

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan> | "
    "{message}"
)

_configured = False


def setup_logger(level: str = "DEBUG") -> None:
    """
    Logger'ı yapılandırır: konsol ve dosya sink'lerini ekler.

    İkinci kez çağrılırsa tekrar yapılandırmaz (idempotent).

    Kullanım:
        >>> from utils.logger import setup_logger
        >>> setup_logger()
    """
    global _configured
    if _configured:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stdout,
        format=_LOG_FORMAT,
        level=level,
        colorize=True,
        enqueue=True,
    )

    logger.add(
        str(_LOG_FILE),
        format=_LOG_FORMAT,
        level=level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )

    _configured = True


def get_logger(module_name: str):
    """
    Belirtilen modül adına bağlı bir loguru logger döndürür.

    Eğer logger henüz yapılandırılmamışsa otomatik olarak setup_logger() çağrılır.

    Args:
        module_name: Genellikle __name__ olarak geçilir.

    Returns:
        loguru Logger nesnesi (bind ile module alanı sabitlenmiş).

    Kullanım:
        >>> from utils.logger import get_logger
        >>> log = get_logger(__name__)
        >>> log.info("Uygulama başlatıldı")
    """
    if not _configured:
        setup_logger()

    return logger.bind(module=module_name)
