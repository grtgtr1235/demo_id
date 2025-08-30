#!/usr/bin/env python3
import argparse, asyncio, json, os, re, time, hashlib
from urllib.parse import quote_plus, urlparse
import feedparser, httpx, pandas as pd, requests, trafilatura, dateparser

# --- NER (spaCy multilingual kecil) ---
import spacy
from spacy.cli import download as spacy_download
_NLP=None
def ensure_nlp():
    global _NLP
    if _NLP is not None: return _NLP
    try: _NLP = spacy.load("xx_ent_wiki_sm")
    except Exception:
        spacy_download("xx_ent_wiki_sm")
        _NLP = spacy.load("xx_ent_wiki_sm")
    return _NLP

# --- Regex alamat Indonesia ---
ADDR_RE = re.compile(
    r"(?:di\s+)?(?:(?:Jl|Jln|Jalan|Gg)\.?\s+[A-Z0-9][^,.;\n]+|Kantor\s+DPRD[^,.;\n]+|DPRD\s+[A-Z][^,.;\n]+|Polres[^,.;\n]+|Polresta[^,.;\n]+|Polda[^,.;\n]+|Mapolda[^,.;\n]+|Gedung\s+DPR[^,.;\n]+)",
    re.I
)

# Landmark sering muncul → direct hit (tanpa geocoder)
PRIORITY_PLACES = {
  "gedung dpr": (-6.2128, 106.8006, "Gedung MPR/DPR/DPD RI, Senayan"),
  "gedung mpr": (-6.2128, 106.8006, "Gedung MPR/DPR/DPD RI, Senayan"),
  "polda metro jaya": (-6.2265, 106.8085, "Polda Metro Jaya"),
  "istana merdeka": (-6.1701, 106.8247, "Istana Merdeka"),
  "monas": (-6.175392, 106.827153, "Monumen Nasional")
}
UA = os.getenv("APP_USER_AGENT", "id-demo-mapper/1.2 (contact: you@example.com)")
PHOTON = "https://photon.komoot.io/api"

# Nominatim sebagai fallback (rate-limit internal via geopy RateLimiter)
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
_GEOCODER = Nominatim(user_agent=UA, timeout=20)
_geocode = RateLimiter(_GEOCODER.geocode, min_delay_seconds=1.1, swallow_exceptions=True)

def gnews_rss(query, when="24h", lang="id", country="ID"):
    q = quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}+when:{when}&hl={lang}&gl={country}&ceid={country}:{lang}"

def parse_date_any(s):
    if not s: return None
    dt = dateparser.parse(s, languages=["id","en"])
    return dt.isoformat() if dt else None

def extract_locs(text):
    nlp = ensure_nlp()
    locs=[]
    if text:
        doc=nlp(text)
        locs += [e.text.strip() for e in doc.ents if e.label_ in ("LOC","GPE")]
        locs += [m.group(0) for m in ADDR_RE.finditer(text)]
    uniq,seen=[],set()
    for l in locs:
        k=l.lower()
        if k not in seen and len(l)>=3:
            uniq.append(l); seen.add(k)
    uniq.sort(key=lambda x:(-len(x),x))
    return uniq

def classify_topic(text):
    s=(text or "").lower()
    if "affan" in s: return "AFFAN"
    if any(k in s for k in ["polisi","brimob","polda","polres","polresta"]): return "POLISI"
    if any(k in s for k in ["dpr","parlemen","gedung dpr"]): return "DPR"
    return "UMUM"

def geo_priority(q_lower):
    for k,(lat,lon,name) in PRIORITY_PLACES.items():
        if k in q_lower:
            return {"lat":lat,"lon":lon,"place_name":name,"geocoder":"priority","score":1.0}

def geo_photon(q, province=None):
    try:
        qs = q if not province else f"{q}, {province}"
        r = requests.get(PHOTON, params={"q":qs,"lang":"id"}, timeout=15, headers={"User-Agent":UA})
        r.raise_for_status()
        feats = r.json().get("features",[])
        if feats:
            f=feats[0]; lon,lat = f["geometry"]["coordinates"]
            p=f.get("properties",{})
            return {"lat":lat,"lon":lon,"geocoder":"photon","score":0.6,
                    "street":p.get("street"),"place_name":p.get("name"),
                    "kecamatan":p.get("city_district") or p.get("suburb"),
                    "kab_kota":p.get("city") or p.get("county"),
                    "provinsi":p.get("state")}
    except Exception: pass

def geo_nominatim(q, province=None):
    try:
        qs = q if not province else f"{q}, {province}"
        res = _geocode(qs, exactly_one=True, addressdetails=True)
        if res:
            a=res.raw.get("address",{})
            return {"lat":res.latitude,"lon":res.longitude,"geocoder":"nominatim","score":0.8,
                    "street":a.get("road") or a.get("pedestrian"),
                    "place_name":a.get("public_building") or a.get("tourism") or a.get("building"),
                    "kecamatan":a.get("suburb") or a.get("city_district") or a.get("district"),
                    "kab_kota":a.get("city") or a.get("county"),
                    "provinsi":a.get("state")}
    except Exception: pass

def geocode_candidates(cands, province=None, cache_path="geocode_cache.json"):
    cache={}
    if os.path.exists(cache_path):
        try: cache=json.load(open(cache_path,"r",encoding="utf-8"))
        except Exception: cache={}
    out={}
    for cand in cands:
        key=cand.lower()+("|"+province.lower() if province else "")
        if key in cache: out[cand]=cache[key]; continue
        hit = geo_priority(key) or geo_photon(cand, province) or geo_nominatim(cand, province)
        out[cand]=hit; cache[key]=hit
        time.sleep(0.1)
    try: json.dump(cache, open(cache_path,"w",encoding="utf-8"))
    except Exception: pass
    return out

async def fetch_html(urls, mode="fast"):
    if mode=="fast": return {u:"" for u in urls}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def one(u):
            try:
                r=await client.get(u, headers={"User-Agent":UA}, timeout=25); r.raise_for_status()
                return u,r.text
            except Exception:
                return u,""
        res=await asyncio.gather(*[one(u) for u in urls])
        return dict(res)

def extract_text(html, url):
    if not html: return ""
    try: return trafilatura.extract(html, include_comments=False, include_tables=False, url=url) or ""
    except Exception: return ""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--include",required=True,help="comma-separated keywords include")
    ap.add_argument("--exclude",default="",help="comma-separated keywords exclude (title only)")
    ap.add_argument("--when",default="24h",help="12h/24h/48h/72h/7d")
    ap.add_argument("--province",default=None,help="bias geocode ke provinsi (mis. 'DKI Jakarta')")
    ap.add_argument("--mode",default="fast",choices=["fast","full"],help="fast=judul saja, full=unduh isi artikel")
    ap.add_argument("--out",default="demo_out.csv")
    args=ap.parse_args()

    inc=[x.strip() for x in args.include.split(",") if x.strip()]
    exc=[x.strip().lower() for x in args.exclude.split(",") if x.strip()]

    topic_core = ["dpr","parlemen","gedung dpr","polisi","polda","polres","brimob","affan"]
    query = " OR ".join(f"({k})" for k in (inc+topic_core))

    feed_url=gnews_rss(query, when=args.when)
    d=feedparser.parse(feed_url)
    rows=[]; urls=[]
    for e in d.entries:
        title=e.title
        if any(x in title.lower() for x in exc): continue
        link=e.link
        published=getattr(e,"published","") or getattr(e,"updated","")
        rows.append({"id":hashlib.md5(link.encode()).hexdigest(),
                     "title":title,"source_url":link,"source_domain":urlparse(link).netloc,
                     "published_at_utc":dateparser.parse(published).isoformat() if published else None})
        urls.append(link)
    if not rows:
        pd.DataFrame([]).to_csv(args.out,index=False); print("No results."); return

    url2html=asyncio.run(fetch_html(urls, mode=args.mode))
    all_cands=set()
    for r in rows:
        body = extract_text(url2html.get(r["source_url"],""), r["source_url"]) if args.mode=="full" else ""
        text=(r["title"] or "")+"\n"+(body or "")
        locs=extract_locs(text)
        r["raw_text"]=body[:1500]; r["key_phrases"]="; ".join(locs[:10]);
        s=text.lower()
        r["topic_tag"]=("AFFAN" if "affan" in s else ("POLISI" if any(k in s for k in ["polisi","brimob","polda","polres","polresta"]) else ("DPR" if any(k in s for k in ["dpr","parlemen","gedung dpr"]) else "UMUM")))
        for l in locs[:6]: all_cands.add(l)

    geo_cache=geocode_candidates(sorted(all_cands,key=lambda x:(-len(x),x)), args.province)
    for r in rows:
        locs=[x.strip() for x in r.get("key_phrases","").split(";") if x.strip()]
        best=None
        for cand in locs[:6]:
            g=geo_cache.get(cand)
            if g: best=(cand,g); break
        if best:
            c,g=best
            r.update({"mention_phrase":c,"lat":g.get("lat"),"lon":g.get("lon"),
                      "geocoder":g.get("geocoder"),"geocode_score":g.get("score"),
                      "street":g.get("street"),"place_name":g.get("place_name"),
                      "kecamatan":g.get("kecamatan"),"kab_kota":g.get("kab_kota"),
                      "provinsi":g.get("provinsi")})
    pd.DataFrame(rows).to_csv(args.out,index=False)
    print(f"Saved: {args.out} rows={len(rows)}")

if __name__=="__main__":
    main()
