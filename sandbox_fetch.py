import asyncio
import json
import os
from dotenv import load_dotenv

# Load .env to get the credentials
load_dotenv()

from fetcher.provider_factory import get_provider

async def main():
    # Force MKK provider for testing if needed, or just let it use the environment variable
    provider = get_provider()
    print(f"Kullanılan provider: {type(provider).__name__}")
    
    # Fetch latest 5 disclosures
    print("Son 5 KAP bildirimi çekiliyor...")
    disclosures = await provider.fetch_latest(limit=5)
    
    # Convert to dict
    data = [d.model_dump(mode='json', by_alias=True) for d in disclosures]
    
    # Save to ornek.json
    output_file = "ornek.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    print(f"{len(data)} adet bildirim {output_file} dosyasına kaydedildi.")
    await provider.close()

if __name__ == "__main__":
    asyncio.run(main())
