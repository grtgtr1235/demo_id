# Demo/Protes Indonesia — Streamlit (Hugging Face Spaces)

App gratis untuk crawling berita demo/protes DPR/Polisi/Affan → ekstraksi lokasi → peta interaktif.

## Jalankan lokal
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy di Hugging Face Spaces
1. Buat Space: https://huggingface.co/spaces → **New Space**
   - **SDK**: Streamlit
   - **Visibility**: Public
2. Upload file: `app.py`, `rss_crawl_fast.py`, `requirements.txt`, `README.md`.
3. Tunggu build → app live di `https://<space-name>.hf.space`.

## Catatan
- Tidak perlu API key (Google News RSS, Photon, Nominatim).
- Geocoding: Photon (cepat) → Nominatim (fallback, ada rate-limit).
- spaCy otomatis unduh model kecil `xx_ent_wiki_sm` saat first-run.
