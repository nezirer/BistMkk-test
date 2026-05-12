from huggingface_hub import hf_hub_download
import time

repo_id = "lm-kit/gemma-3-12b-instruct-gguf"
filename = "gemma-3-it-12B-Q4_K_M.gguf"

print("Gemma-3 GGUF model indirmesi başlatılıyor...")
start_time = time.time()

try:
    path = hf_hub_download(repo_id=repo_id, filename=filename)
    end_time = time.time()
    print(f"Model başarıyla indirildi: {path}")
    print(f"İndirme süresi: {end_time - start_time:.2f} saniye")
except Exception as e:
    print(f"Hata: {e}")
