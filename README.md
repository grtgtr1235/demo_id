# Demo/Protes Indonesia — Streamlit (spaCy build)

- Crawler: Google News RSS → ekstraksi lokasi (spaCy NER + regex) → geocoding (Photon→Nominatim) → peta.
- spaCy model `xx_ent_wiki_sm` di-install saat build melalui `requirements.txt`.
- `runtime.txt` memaksa Python 3.11 untuk kompatibilitas wheel.

## Lokal
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
