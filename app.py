import streamlit as st, pandas as pd, subprocess, sys, os
from streamlit_folium import st_folium
import folium
from folium.plugins import MarkerCluster

st.set_page_config(page_title="Peta Demo/Protes Indonesia", layout="wide")
st.title("Peta Demo/Protes Indonesia (Crawler Gratis)")

with st.sidebar:
    st.header("Filter Crawling")
    inc = st.text_input("Keyword include (koma)", "demo,protes,kerusuhan")
    when = st.selectbox("Rentang waktu", ["12h","24h","48h","72h","7d"], index=1)
    province = st.text_input("Bias provinsi (opsional)", "")
    mode = st.radio("Mode crawling", ["fast (judul)", "full (ambil isi)"], index=0)
    run = st.button("Jalankan Crawling")

def draw_map(df):
    m = folium.Map(location=[-2.5,117], zoom_start=5, control_scale=True)
    if df is not None and not df.empty and {"lat","lon"}.issubset(df.columns):
        mc = MarkerCluster().add_to(m)
        for _,r in df.dropna(subset=["lat","lon"]).iterrows():
            popup = folium.Popup(f"""
            <b>{r.get('title','')}</b><br>
            <i>{r.get('mention_phrase','')}</i><br>
            {(r.get('street') or r.get('place_name') or '')}<br>
            {(r.get('kecamatan','') or '')}, {(r.get('kab_kota','') or '')}, {(r.get('provinsi','') or '')}<br>
            <a href="{r.get('source_url','')}" target="_blank">Baca sumber</a>
            """, max_width=350)
            folium.Marker([r["lat"], r["lon"]],
                          tooltip=r.get("topic_tag",""), popup=popup).add_to(mc)
    st_folium(m, height=650, use_container_width=True)

if run:
    out = "result.csv"
    cmd = [sys.executable, "rss_crawl_fast.py", "--include", inc, "--when", when, "--mode", "fast" if mode.startswith("fast") else "full", "--out", out]
    if province.strip():
        cmd += ["--province", province.strip()]
    with st.spinner("Crawling..."):
        subprocess.run(cmd, check=False)
    st.success("Selesai. Hasil terbaru di bawah.")
    if os.path.exists(out):
        df = pd.read_csv(out)
        st.dataframe(df[["published_at_utc","title","topic_tag","mention_phrase","kecamatan","kab_kota","provinsi","source_domain"]], use_container_width=True)
        draw_map(df)
    else:
        st.warning("Tidak ada file hasil.")
else:
    st.info("Isi filter di kiri dan klik 'Jalankan Crawling'.")
    draw_map(pd.DataFrame())  # tampilkan basemap dulu

st.markdown("---")
st.caption("Tips: tambah kata kunci seperti 'DPR', 'DPRD', 'Polda', 'Polres', 'Senayan', 'Affan'.")
