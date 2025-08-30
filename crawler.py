import os, time, re, json, hashlib, requests, feedparser, pandas as pd
from urllib.parse import quote_plus, urlparse
from datetime import datetime, timezone
import trafilatura
import dateparser

# ---------- NER: spaCy multilingual (lebih ringan daripada Stanza) ----------
import spacy
from spacy.cli import download as spacy_download
_NLP_READY = False
def _ensure_nlp():
    global _NLP_READY, nlp
    if _NLP_READY: return
    try:
        nlp = spacy.load("xx_ent_wiki_sm")
    except Exception:
        spacy_download("xx_ent_wiki_sm")
        nlp = spacy.load("xx_ent_wiki_sm")
    _NLP_READY = True

# Geocoding
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

UA = os.getenv("APP_USER_AGENT", "id-demo-mapper/1.1 (contact: you@example.com)")

# Kamus lokasi prioritas (perkuat sesuai kebutuhan)
PRIORITY_PLACES = {
  "gedung dpr": {"lat": -6.2128, "lon": 106.8006, "place_name": "Gedung MPR/DPR/DPD RI, Senayan"},
  "gedung mpr": {"lat": -6.2128, "lon": 106.8006, "place_name": "Gedung MPR/DPR/DPD RI, Senayan"},
  "kompleks senayan": {"lat": -6.2186, "lon": 106.8011, "place_name": "Kompleks GBK Senayan"},
  "polda metro jaya": {"lat": -6.2265, "lon": 106.8085, "place_name": "Polda Metro Jaya"},
  "istana merdeka": {"lat": -6.1701, "lon": 106.8247, "place_name": "Istana Merdeka"},
  "monas": {"lat": -6.175392, "lon": 106.827153, "place_name": "Monumen Nasional"}
}

# Pola alamat Indonesia (ringkas, bisa diperluas)
ADDR_RE = re.compile(
    r"(?:di\s+)?(?:(?:Jl|Jln|Jalan|Gg)\.?\s+[A-Z0-9][^,.;\n]+|Kantor\s+DPRD[^,.;\n]+|DPRD\s+[A-Z][^,.;\n]+|Polres[^,.;\n]+|Polresta[^,.;\n]+|Polda[^,.;\n]+|Mapolda[^,.;\n]+|Gedung\s+DPR[^,.;\n]+)",
    re.I
)

def google_news_rss(query, when=None, after=None, before=None, lang="id", country="ID"):
    base = "https://news.google.com/rss/search?q="
    from urllib.parse import quote_plus
    q = quote_plus(query)
    parts = [q]
    if when: parts.append(f"when:{when}")
    if after and before:
        parts.append(f"after:{after}")
        parts.append(f"before:{before}")
    return f"{base}{'+'.join(parts)}&hl={lang}&gl={country}&ceid={country}:{lang}"

def fetch_rss(url):
    d = feedparser.parse(url)
    for e in d.entries:
        yield {
            "title": e.title,
            "link": e.link,
            "published": getattr(e, "published", "") or getattr(e, "updated", ""),
            "source": url
        }

def get_article(url, user_agent=UA):
    try:
        r = requests.get(url, headers={"User-Agent": user_agent}, timeout=25)
        r.raise_for_status()
        return trafilatura.extract(r.text, include_comments=False, include_tables=False, url=url) or ""
    except Exception:
        return ""

def parse_date(text):
    if not text: return None
    dt = dateparser.parse(text, languages=["id","en"])
    if not dt: return None
    return dt.astimezone(timezone.utc).isoformat()

def nlp_locations(text):
    _ensure_nlp()
    doc = nlp(text)
    locs = [ent.text.strip() for ent in doc.ents if ent.label_ in ("LOC","GPE")]
    locs += [m.group(0) for m in ADDR_RE.finditer(text)]
    # Dedup
    uniq, seen = [], set()
    for l in locs:
        key = l.lower()
        if key not in seen and len(l)>=3:
            uniq.append(l); seen.add(key)
    uniq.sort(key=lambda x: (-len(x), x))
    return uniq

# Geocoder setup (Nominatim + RateLimiter)
geocoder = Nominatim(user_agent=UA, timeout=20)
geocode = RateLimiter(geocoder.geocode, min_delay_seconds=1.1, swallow_exceptions=True)

PHOTON_URL = "https://photon.komoot.io/api"

def geocode_text(q, bias_bbox=None):
    # 1) Priority dictionary
    key = q.lower()
    for k,v in PRIORITY_PLACES.items():
        if k in key:
            return {**v, "geocoder":"priority", "score":1.0}
    # 2) Nominatim
    try:
        params = {"addressdetails": 1}
        if bias_bbox:
            params["viewbox"] = ",".join(map(str, bias_bbox))
            params["bounded"] = 1
        res = geocode(q, exactly_one=True, addressdetails=True, **params)
        if res:
            d = res.raw.get("address", {})
            return {
                "lat": res.latitude, "lon": res.longitude, "geocoder":"nominatim", "score":0.8,
                "road": d.get("road") or d.get("pedestrian"),
                "place_name": d.get("public_building") or d.get("tourism") or d.get("building"),
                "kecamatan": d.get("suburb") or d.get("city_district") or d.get("district"),
                "kab_kota": d.get("city") or d.get("county"),
                "provinsi": d.get("state")
            }
    except Exception:
        pass
    # 3) Photon fallback
    try:
        r = requests.get(PHOTON_URL, params={"q": q, "lang":"id"}, timeout=15)
        r.raise_for_status()
        js = r.json()
        feats = js.get("features", [])
        if feats:
            f = feats[0]
            lon, lat = f["geometry"]["coordinates"]
            props = f.get("properties", {})
            return {
                "lat": lat, "lon": lon, "geocoder":"photon", "score":0.6,
                "road": props.get("street"), "place_name": props.get("name"),
                "kecamatan": props.get("city_district") or props.get("suburb"),
                "kab_kota": props.get("city") or props.get("county"),
                "provinsi": props.get("state")
            }
    except Exception:
        pass
    return None

def classify_topic(text):
    s = (text or "").lower()
    if "affan" in s: return "AFFAN"
    if any(k in s for k in ["polisi","brimob","polda","polres","polresta"]): return "POLISI"
    if any(k in s for k in ["dpr","parlemen","gedung dpr"]): return "DPR"
    return "UMUM"

def crawl_once(keywords_include, keywords_exclude=None, when="72h", province_bias=None):
    must = " OR ".join([f"({k})" for k in keywords_include])
    url = google_news_rss(must, when=when)
    rows = []
    for item in fetch_rss(url):
        title = item["title"]
        if keywords_exclude and any(x.lower() in title.lower() for x in keywords_exclude):
            continue
        text = get_article(item["link"])
        published = parse_date(item["published"])
        fulltext = f"{title}\n{text}"
        locs = nlp_locations(fulltext)
        best_hit = None
        for cand in locs[:6]:
            g = geocode_text(cand, bias_bbox=province_bias)
            if g:
                best_hit = (cand, g); break
        rec = {
            "id": hashlib.md5(item["link"].encode()).hexdigest(),
            "source_url": item["link"],
            "source_domain": urlparse(item["link"]).netloc,
            "title": title, "published_at_utc": published,
            "raw_text": text[:2000],
            "key_phrases": "; ".join(locs[:10]),
            "topic_tag": classify_topic(fulltext)
        }
        if best_hit:
            mention, g = best_hit
            rec.update({
                "mention_phrase": mention,
                "lon": g["lon"], "lat": g["lat"], "geocoder": g["geocoder"], "geocode_score": g["score"],
                "street": g.get("road"), "place_name": g.get("place_name"),
                "kecamatan": g.get("kecamatan"), "kab_kota": g.get("kab_kota"), "provinsi": g.get("provinsi")
            })
        rows.append(rec)
        time.sleep(0.3)
    return pd.DataFrame(rows)
