import streamlit as st, pandas as pd, subprocess, sys, os
import folium
from folium.plugins import MarkerCluster

# =========================
# Render peta: streamlit_folium jika ada; fallback ke components.html
# =========================
try:
    from streamlit_folium import st_folium
    def render_map(m): st_folium(m, height=650, use_container_width=True)
except Exception:
    import streamlit.components.v1 as components
    def render_map(m): components.html(m._repr_html_(), height=650, scrolling=False)

# =========================
# Konfigurasi umum
# =========================
RESULT_PATH = "result.csv"

st.set_page_config(page_title="Peta Demo/Protes Indonesia", layout="wide")
st.title("Peta Demo/Protes Indonesia (News Crawler)")

# =========================
# Sidebar (kontrol crawling)
# =========================
with st.sidebar:
    st.header("Filter Crawling")
    inc = st.text_input("Keyword include (koma)", "demo,protes,kerusuhan")
    when = st.selectbox("Rentang waktu", ["12h","24h","48h","72h","7d"], index=1)
    province = st.text_input("Bias provinsi (opsional)", "")
    mode = st.radio("Mode crawling", ["fast (judul)", "full (ambil isi)"], index=0)
    id_only = st.checkbox("Hanya media Indonesia", value=True)
    run = st.button("Jalankan Crawling")

# =========================
# Helpers
# =========================
def run_crawl():
    """Jalankan crawler sebagai proses terpisah."""
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

def load_df() -> pd.DataFrame:
    """Muat CSV hasil crawling. Aman jika file kosong/belum ada. Pastikan kolom UTC tz-aware."""
    if not os.path.exists(RESULT_PATH) or os.path.getsize(RESULT_PATH) == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(RESULT_PATH)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

    if "published_at_utc" in df.columns:
        # pastikan tz-aware UTC
        df["published_at_utc"] = pd.to_datetime(df["published_at_utc"], errors="coerce", utc=True)
    return df

def draw_map(df: pd.DataFrame):
    m = folium.Map(location=[-2.5, 117], zoom_start=5, control_scale=True)
    if df is not None and not df.empty and {"lat","lon"}.issubset(df.columns):
        mc = MarkerCluster().add_to(m)
        for _, r in df.dropna(subset=["lat","lon"]).iterrows():
            popup = folium.Popup(f"""
                <b>{r.get('title','')}</b><br>
                <small>{r.get('published_at_utc')}</small><br>
                <i>{r.get('mention_phrase','')}</i><br>
                {(r.get('street') or r.get('place_name') or '')}<br>
                {(r.get('kecamatan','') or '')}, {(r.get('kab_kota','') or '')}, {(r.get('provinsi','') or '')}<br>
                <a href="{r.get('source_url','')}" target="_blank">Baca sumber</a>
            """, max_width=350)
            folium.Marker(
                [r["lat"], r["lon"]],
                tooltip=r.get("topic_tag",""),
                popup=popup
            ).add_to(mc)
    render_map(m)

# =========================
# Eksekusi crawling bila tombol ditekan
# =========================
if run:
    run_crawl()
    st.success("Selesai. Hasil terbaru di bawah.")

# =========================
# Muat data & UI (Tabs)
# =========================
df = load_df()
tab_map, tab_table = st.tabs(["🗺️ Peta", "📊 Tabel"])

with tab_map:
    if df.empty:
        st.warning("Belum ada data. Klik **Jalankan Crawling** di sidebar.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Total artikel", len(df))
        with c2: st.metric("Titik tergeocode", int(df[["lat","lon"]].notna().all(axis=1).sum()))
        with c3: st.metric("Sumber unik", df["source_domain"].nunique() if "source_domain" in df.columns else 0)
        draw_map(df)

with tab_table:
    if df.empty:
        st.info("Belum ada data untuk ditampilkan.")
    else:
        # ---------- Filter tabel ----------
        col1, col2, col3 = st.columns([1,1,2])
        with col1:
            topics = sorted(df["topic_tag"].dropna().unique()) if "topic_tag" in df.columns else []
            sel_topics = st.multiselect("Filter topik", topics, default=topics)
        with col2:
            provs = sorted(df["provinsi"].dropna().unique()) if "provinsi" in df.columns else []
            sel_prov = st.multiselect("Filter provinsi", provs, default=provs[:10] if len(provs)>10 else provs)
        with col3:
            if "published_at_utc" in df.columns and df["published_at_utc"].notna().any():
                min_d = pd.to_datetime(df["published_at_utc"].min()).date()
                max_d = pd.to_datetime(df["published_at_utc"].max()).date()
                dr = st.date_input("Rentang tanggal (UTC)", (min_d, max_d))
            else:
                dr = None

        df_f = df.copy()
        if "topic_tag" in df_f.columns and sel_topics:
            df_f = df_f[df_f["topic_tag"].isin(sel_topics)]
        if "provinsi" in df_f.columns and sel_prov:
            df_f = df_f[df_f["provinsi"].isin(sel_prov)]

        # Filter tanggal: semua tz-aware UTC (hindari TypeError)
        if dr and isinstance(dr, tuple) and len(dr) == 2 and "published_at_utc" in df_f.columns:
            start = pd.Timestamp(dr[0], tz="UTC")
            end = pd.Timestamp(dr[1], tz="UTC") + pd.Timedelta(days=1)  # end eksklusif
            df_f = df_f[(df_f["published_at_utc"] >= start) & (df_f["published_at_utc"] < end)]

        show_cols = [c for c in [
            "published_at_utc","title","topic_tag","mention_phrase",
            "street","place_name","kecamatan","kab_kota","provinsi",
            "geocoder","geocode_score","source_domain","source_url"
        ] if c in df_f.columns]

        st.dataframe(
            df_f[show_cols].sort_values("published_at_utc", ascending=False, na_position="last"),
            use_container_width=True, height=520
        )

        st.download_button(
            "⬇️ Unduh CSV (hasil filter, UTC)",
            data=df_f[show_cols].to_csv(index=False).encode("utf-8"),
            file_name="demo_crawl_utc_filtered.csv",
            mime="text/csv"
        )

st.markdown("---")
st.caption("Waktu ditampilkan & difilter dalam UTC. Centang 'Hanya media Indonesia' agar domain non-ID disaring.")
