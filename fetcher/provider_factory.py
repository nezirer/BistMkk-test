import os

from fetcher.base_provider import BaseKAPProvider


def get_provider() -> BaseKAPProvider:
    """
    KAP_PROVIDER ortam değişkenine göre doğru provider'ı döndürür.

    .env içinde:
    KAP_PROVIDER=mock    → MockProvider (geliştirme)
    KAP_PROVIDER=mkk     → MKKProvider (production)
    """
    provider_type = os.getenv("KAP_PROVIDER", "mock").lower()

    if provider_type == "mkk":
        from fetcher.mkk_provider import MKKProvider
        return MKKProvider()
    else:
        from fetcher.mock_provider import MockProvider
        return MockProvider()
