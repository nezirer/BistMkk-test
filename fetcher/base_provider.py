from abc import ABC, abstractmethod
from models.disclosure import DisclosureRaw


class BaseKAPProvider(ABC):
    """
    Tüm KAP veri sağlayıcıları bu arayüzü implement etmeli.
    Yeni provider eklemek için sadece bu class'ı extend et.
    """

    @abstractmethod
    async def fetch_latest(self, limit: int = 50) -> list[DisclosureRaw]:
        """Son N bildirimi döndürür."""
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
