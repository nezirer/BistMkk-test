import asyncio
from db.connection import get_connection, init_pool, close_pool

async def reset_prices():
    init_pool()
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        def _update(conn):
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kap_disclosures
                    SET price_at_news = NULL,
                        price_5m = NULL,
                        price_1h = NULL,
                        price_1d = NULL,
                        price_1w = NULL
                """)
                return cur.rowcount
        rowcount = await loop.run_in_executor(None, _update, conn)
        print(f"Başarıyla {rowcount} bildirimin fiyat verileri sıfırlandı.")
    close_pool()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(reset_prices())
