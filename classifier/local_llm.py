import os
from huggingface_hub import hf_hub_download
from llama_cpp import Llama
from utils.logger import get_logger

log = get_logger(__name__)

_summarizer_llm = None

def get_summarizer():
    global _summarizer_llm
    if _summarizer_llm is None:
        repo_id = "lm-kit/gemma-3-12b-instruct-gguf"
        filename = "gemma-3-it-12B-Q4_K_M.gguf"
        
        log.info(f"Yükleniyor (GGUF Özetleyici): {repo_id} / {filename}")
        try:
            # Model dosyasını indir (eğer inmemişse) ve yolunu al
            model_path = hf_hub_download(repo_id=repo_id, filename=filename)
            log.info(f"Model dosyası bulundu/indirildi: {model_path}")
            
            # GGUF Modelini Llama.cpp ile yükle
            # n_gpu_layers=-1 ile Apple Silicon (Metal) GPU hızlandırması aktif edilir
            # n_ctx bağlam sınırıdır, PDF'ler uzun olabileceği için 4096 veriyoruz
            _summarizer_llm = Llama(
                model_path=model_path,
                n_gpu_layers=-1, 
                n_ctx=4096,      
                verbose=False    # Konsol kirliliğini önlemek için
            )
            log.info("GGUF modeli başarıyla yüklendi (Metal/GPU desteği aktif).")
        except Exception as e:
            log.error(f"GGUF model yükleme hatası: {e}")
            raise e
    return _summarizer_llm

async def generate_summary(text: str) -> str:
    """
    Belirtilen metni Gemma-3 GGUF modelini kullanarak özetler.
    """
    if not text:
        return "Metin bulunamadı."
        
    try:
        llm = get_summarizer()
        
        messages = [
            {"role": "system", "content": "Sen bir finansal veri çıkarma ve özetleme uzmanısın. BIST KAP üzerinden gelen metinlerin en önemli finansal ve operasyonel bilgilerini kısaca özetlersin."},
            {"role": "user", "content": f"Aşağıdaki finansal metni analiz et ve kısaca özetle. Lütfen sadece özeti ver, ek yorum yapma:\n\n{text[:10000]}"}
        ]
        
        log.info("Özetleme için GGUF modeli çalıştırılıyor...")
        response = llm.create_chat_completion(
            messages=messages,
            max_tokens=300,
            temperature=0.0
        )
        
        summary = response['choices'][0]['message']['content'].strip()
        log.info("Özetleme başarıyla tamamlandı.")
        return summary
    except Exception as e:
        log.error(f"Özetleme işlemi hatası: {e}")
        return "Özetleme işlemi başarısız."
