import asyncio
from db.connection import get_connection, init_pool, close_pool
from main import _backfill_publish_datetime, _update_prices
import db.repository as repo

async def run_backfill():
    init_pool()
    print("Fiyat backfill işlemi başlatılıyor...")
    # Sınırı artırarak hepsini tek seferde çekelim
    # _backfill_publish_datetime 50 limit kullanıyor, bu yüzden birkaç kez çağırabiliriz.
    for i in range(3):
        print(f"Adım {i+1}/3: Yayın anı fiyatları çekiliyor...")
        await _backfill_publish_datetime()
        
    print("Gelecek fiyatları (5dk, 1sa vb.) hesaplanıyor...")
    await _update_prices()
    
    print("İşlem tamamlandı.")
    close_pool()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(run_backfill())
