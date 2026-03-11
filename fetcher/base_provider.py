from abc import ABC, abstractmethod
from models.disclosure import DisclosureRaw


class BaseKAPProvider(ABC):
    """
    Tüm KAP veri sağlayıcıları bu arayüzü implement etmeli.
    Yeni provider eklemek için sadece bu class'ı extend et.
    """

    @abstractmethod
    async def fetch_latest(self, limit: int = 50, since_index: int = 0) -> list[DisclosureRaw]:
        """
        Son bildirimleri döndürür.
        since_index > 0 ise yalnızca o index'ten büyük olanlar çekilir
        (API rate limit koruması).
        """
        ...

    @abstractmethod
    async def fetch_by_stock_code(self, code: str) -> list[DisclosureRaw]:
        """Hisse koduna göre bildirimleri döndürür."""
        ...

    @abstractmethod
    async def fetch_companies(self) -> list[dict]:
        """Tüm şirket listesini döndürür."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Provider'ın erişilebilir olup olmadığını kontrol eder."""
        ...

    async def close(self) -> None:
        """Provider kaynaklarını serbest bırakır (HTTP client vb.)."""
