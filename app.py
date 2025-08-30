import streamlit as st, pandas as pd, subprocess, sys, os
import folium
from folium.plugins import MarkerCluster
from zoneinfo import ZoneInfo

# Folium renderer: prefer streamlit_folium; fallback ke components.html
try:
    from streamlit_folium import st_folium
    def render_map(m): st_folium(m, height=650, use_container_width=True)
except Exception:
    import streamlit.components.v1 as components
    def render_map(m): components.html(m._repr_html_(), height=650, scrolling=False)

TZ = ZoneInfo("Asia/Jakarta")  # GMT+7

st.set_page_config(page_title="Peta Demo/Protes Indonesia", layout="wide")
st.title("Peta Demo/Protes Indonesia (News Crawler)")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Filter Crawling")
    inc = st.text_input("Keyword include (koma)", "demo,protes,kerusuhan")
    when = st.selectbox("Rentang waktu", ["12h","24h","48h","72h","7d"], index=1)
    province = st.text_input("Bias provinsi (opsional)", "")
    mode = st.radio("Mode crawling", ["fast (judul)", "full (ambil isi)"], index=0)
    id_only = st.checkbox("Hanya media Indonesia", value=True)
    run = st.button("Jalankan Crawling")

RESULT_PATH = "result.csv"

def run_crawl():
    cmd = [sys.executable, "rss_crawl_fast.py",
           "--include", inc,
           "--when", when,
           "--mode", "fast" if mode.startswith("fast") else "full",
           "--out", RESULT_PATH]
    if province.strip():
        cmd += ["--province", province.strip()]
    if id_only:
        cmd += ["--id-media-only"]
    with st.spinner("Crawling..."):
        subprocess.run(cmd, check=False)

def load_df():
    if not os.path.exists(RESULT_PATH):
        return pd.DataFrame()
    df = pd.read_csv(RESULT_PATH)
    # published_at_utc -> datetime UTC → kolom lokal (GMT+7) untuk filter/tampilan
    if "published_at_utc" in df.columns:
        utc = pd.to_datetime(df["published_at_utc"], errors="coerce", utc=True)
        df["published_at_utc"] = utc
        df["published_at_gmt7"] = utc.dt.tz_convert(TZ)
    return df

def draw_map(df):
    m = folium.Map(location=[-2.5,117], zoom_start=5, control_scale=True)
    if df is not None and not df.empty and {"lat","lon"}.issubset(df.columns):
        mc = MarkerCluster().add_to(m)
        for _,r in df.dropna(subset=["lat","lon"]).iterrows():
            popup = folium.Popup(f"""
                <b>{r.get('title','')}</b><br>
                <small>{r.get('published_at_gmt7')}</small><br>
                <i>{r.get('mention_phrase','')}</i><br>
                {(r.get('street') or r.get('place_name') or '')}<br>
                {(r.get('kecamatan','') or '')}, {(r.get('kab_kota','') or '')}, {(r.get('provinsi','') or '')}<br>
                <a href="{r.get('source_url','')}" target="_blank">Baca sumber</a>
            """, max_width=350)
            folium.Marker([r["lat"], r["lon"]],
                          tooltip=r.get("topic_tag",""), popup=popup).add_to(mc)
    render_map(m)

# Run crawl bila diminta
if run:
    run_crawl()
    st.success("Selesai. Hasil terbaru di bawah.")

df = load_df()

# Tabs Peta / Tabel
tab_map, tab_table = st.tabs(["🗺️ Peta", "📊 Tabel"])

with tab_map:
    if df.empty:
        st.warning("Belum ada data. Klik **Jalankan Crawling** di sidebar.")
    else:
        c1,c2,c3 = st.columns(3)
        with c1: st.metric("Total artikel", len(df))
        with c2: st.metric("Titik tergeocode", int(df[["lat","lon"]].notna().all(axis=1).sum()))
        with c3: st.metric("Sumber unik", df["source_domain"].nunique() if "source_domain" in df.columns else 0)
        draw_map(df)

with tab_table:
    if df.empty:
        st.info("Belum ada data untuk ditampilkan.")
    else:
        # --------- Filter tabel ---------
        col1, col2, col3 = st.columns([1,1,2])
        with col1:
            topics = sorted([x for x in df.get("topic_tag", pd.Series()).dropna().unique()]) if "topic_tag" in df.columns else []
            sel_topics = st.multiselect("Filter topik", topics, default=topics)
        with col2:
            provs = sorted([x for x in df.get("provinsi", pd.Series()).dropna().unique()]) if "provinsi" in df.columns else []
            sel_prov = st.multiselect("Filter provinsi", provs, default=provs[:10] if len(provs)>10 else provs)
        with col3:
            if "published_at_gmt7" in df.columns and df["published_at_gmt7"].notna().any():
                min_d = pd.to_datetime(df["published_at_gmt7"].min()).date()
                max_d = pd.to_datetime(df["published_at_gmt7"].max()).date()
                dr = st.date_input("Rentang tanggal (GMT+7)", (min_d, max_d))
            else:
                dr = None

        df_f = df.copy()
        if "topic_tag" in df_f.columns and sel_topics:
            df_f = df_f[df_f["topic_tag"].isin(sel_topics)]
        if "provinsi" in df_f.columns and sel_prov:
            df_f = df_f[df_f["provinsi"].isin(sel_prov)]
        if dr and isinstance(dr, tuple) and len(dr) == 2 and "published_at_gmt7" in df_f.columns:
            # Buat batas start/end timezone-aware GMT+7
            start = pd.to_datetime(dr[0]).tz_localize(TZ)
            # end di-set ke akhir hari
            end = (pd.to_datetime(dr[1]) + pd.Timedelta(days=1)).tz_localize(TZ)
            df_f = df_f[(df_f["published_at_gmt7"] >= start) & (df_f["published_at_gmt7"] < end)]

        show_cols = [c for c in [
            "published_at_gmt7","title","topic_tag","mention_phrase",
            "street","place_name","kecamatan","kab_kota","provinsi",
            "geocoder","geocode_score","source_domain","source_url"
        ] if c in df_f.columns]
        st.dataframe(df_f[show_cols].sort_values("published_at_gmt7", ascending=False, na_position="last"),
                     use_container_width=True, height=520)

        st.download_button(
            "⬇️ Unduh CSV (hasil filter, GMT+7)",
            data=df_f[show_cols].to_csv(index=False).encode("utf-8"),
            file_name="demo_crawl_gmt7_filtered.csv",
            mime="text/csv"
        )

st.markdown("---")
st.caption("Waktu ditampilkan di GMT+7 (Asia/Jakarta). Sumber dibatasi ke media Indonesia bila opsi dicentang.")
