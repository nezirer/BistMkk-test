"""
KAP–BIST Korelasyon Analiz Modülü

Bu modül, KAP bildirimleri ile BIST hisse senedi fiyat hareketleri
arasındaki korelasyonu istatistiksel olarak inceler.

Kullanım:
    # Standalone çalıştırma:
    python -m analysis.run

    # FastAPI üzerinden:
    GET /analysis          → Dashboard
    GET /api/analysis/*    → JSON API endpoint'leri
"""
