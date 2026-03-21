"""
PostgreSQL veritabanı bağlantı yönetimi.

psycopg2 kullanılır (sync API, asyncio executor ile sarılır).
Bağlantı bilgileri .env dosyasından okunur:

  PG_HOST     = localhost           (Docker içinden erişim)
  PG_PORT     = 5432
  PG_DB       = kap_db
  PG_USER     = kap_user
  PG_PASSWORD = <şifreniz>
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncGenerator

import psycopg2
import psycopg2.pool
from pydantic_settings import BaseSettings

from utils.logger import get_logger

log = get_logger(__name__)


class PGSettings(BaseSettings):
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "kap_db"
    pg_user: str = "kap_user"
    pg_password: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def _get_settings() -> PGSettings:
    return PGSettings()


_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    """Lifespan başlangıcında çağrılır."""
    global _pool
    s = _get_settings()

    if not s.pg_password:
        raise ValueError(
            "PostgreSQL bağlantı bilgileri eksik. "
            ".env dosyasında PG_PASSWORD tanımlı olmalı."
        )

    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        host=s.pg_host,
        port=s.pg_port,
        dbname=s.pg_db,
        user=s.pg_user,
        password=s.pg_password,
        connect_timeout=10,
        options="-c client_encoding=UTF8",
    )
    log.info(
        "PostgreSQL bağlantı havuzu oluşturuldu ({}:{}/{}, kullanıcı: {}).",
        s.pg_host, s.pg_port, s.pg_db, s.pg_user,
    )


def close_pool() -> None:
    """Lifespan sonunda çağrılır."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        log.info("PostgreSQL bağlantı havuzu kapatıldı.")


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    if _pool is None:
        raise RuntimeError("PostgreSQL bağlantı havuzu başlatılmamış. init_pool() çağrılmalı.")
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncGenerator[psycopg2.extensions.connection, None]:
    """
    Async context manager — bağlantıyı asyncio thread pool üzerinden açar.
    Başarıda commit, hata durumunda rollback yapar ve bağlantıyı havuza iade eder.

    Kullanım:
        async with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    loop = asyncio.get_running_loop()
    conn: psycopg2.extensions.connection = await loop.run_in_executor(
        None, get_pool().getconn
    )
    try:
        yield conn
    except Exception:
        await loop.run_in_executor(None, conn.rollback)
        raise
    else:
        await loop.run_in_executor(None, conn.commit)
    finally:
        await loop.run_in_executor(None, get_pool().putconn, conn)
