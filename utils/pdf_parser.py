import httpx
import fitz  # PyMuPDF
from utils.logger import get_logger
from fetcher.mkk_provider import MKKSettings

log = get_logger(__name__)

async def extract_text_from_pdf_url(pdf_url: str) -> str | None:
    """
    Belirtilen URL'den PDF dosyasını asenkron olarak indirir ve
    içerisindeki metni PyMuPDF kullanarak çıkarır. API yetkilendirmesi kullanır.
    """
    try:
        settings = MKKSettings()
        is_prod = settings.mkk_env.lower() in ("prod", "production")
        auth = httpx.BasicAuth(username=settings.mkk_api_user, password=settings.mkk_api_pass)
        
        # Linkte vykapialpha gibi ulaşılamayan eski test sunucusu varsa yenisiyle değiştir
        if "vykapialpha.mkk.com.tr" in pdf_url:
            base_api = settings.mkk_api_base_url.rstrip("/")
            pdf_url = pdf_url.replace("https://vykapialpha.mkk.com.tr/api/vyk", base_api)
        
        headers = {"Accept": "application/pdf, application/octet-stream, */*"}
        if is_prod and settings.mkk_bearer_token:
            headers["Authorization"] = f"Bearer {settings.mkk_bearer_token}"

        async with httpx.AsyncClient(auth=auth, headers=headers, timeout=60.0, verify=False, follow_redirects=True) as client:
            response = await client.get(pdf_url)
            
            if response.status_code != 200:
                log.error("PDF download failed with status {}: {}", response.status_code, response.text)
                
            response.raise_for_status()
            pdf_bytes = response.content

            text = ""
            # PyMuPDF ile hafızadan oku
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                for page in doc:
                    text += page.get_text("text") + "\n"
            
            text = text.strip()
            if not text:
                text = "No text extracted (Possible Image PDF)"
                
            return text
            
    except Exception as exc:
        log.error("PDF indirme/ayrıştırma hatası (URL: {}): {}", pdf_url, exc)
        return None
