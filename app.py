import streamlit as st, pandas as pd
from crawler import crawl_once
from streamlit_folium import st_folium
import folium
from folium.plugins import MarkerCluster

st.set_page_config(page_title="ID Demo Mapper", layout="wide")
st.title("Peta Demo/Protes Indonesia (Crawler Gratis)")

with st.sidebar:
    st.header("Filter")
    inc = st.text_input("Keyword (include, pisahkan dengan koma)",
                        "demo, protes, kerusuhan")
    scope = st.selectbox("Fokus isu", ["Semua","DPR","POLISI","AFFAN"])
    exc = st.text_input("Keyword (exclude, opsional)", "")
    when = st.selectbox("Rentang waktu", ["12h","24h","48h","72h","7d"], index=3)
    st.caption("Gunakan rentang sempit untuk build lebih cepat.")
    run = st.button("Jalankan Crawler")

@st.cache_data(show_spinner=True)
def run_crawl(inc, exc, when):
    inc_list = [x.strip() for x in inc.split(",") if x.strip()]
    exc_list = [x.strip() for x in exc.split(",") if x.strip()]
    df = crawl_once(inc_list, exc_list, when=when, province_bias=None)
    return df

if run:
    df = run_crawl(inc, exc, when)
    if len(df)==0:
        st.warning("Tidak ada hasil. Coba perluas kata kunci atau rentang waktu.")
    else:
        if scope != "Semua":
            df = df[df["topic_tag"] == scope]
        st.success(f"Total hasil: {len(df)}")
        show_cols = ["published_at_utc","title","topic_tag","mention_phrase","kecamatan","kab_kota","provinsi","source_domain"]
        st.dataframe(df[show_cols], use_container_width=True)

        # Peta
        m = folium.Map(location=[-2.5, 117], zoom_start=5, control_scale=True)
        mc = MarkerCluster().add_to(m)
        for _,r in df.dropna(subset=["lat","lon"]).iterrows():
            popup = folium.Popup('''
            <b>{title}</b><br>
            <i>{mention}</i><br>
            {street_or_place}<br>
            {kecamatan}, {kabkota}, {prov}<br>
            <a href="{url}" target="_blank">Baca sumber</a>
            '''.format(
                title=r['title'],
                mention=(r.get('mention_phrase','') or ''),
                street_or_place=(r.get('street') or r.get('place_name') or ''),
                kecamatan=(r.get('kecamatan','') or ''),
                kabkota=(r.get('kab_kota','') or ''),
                prov=(r.get('provinsi','') or ''),
                url=r['source_url']
            ), max_width=350)
            folium.Marker([r["lat"], r["lon"]],
                          tooltip=r["topic_tag"], popup=popup).add_to(mc)
        st_folium(m, height=650, use_container_width=True)

        st.download_button("Unduh CSV", df.to_csv(index=False).encode("utf-8"),
                           "demo_mapper.csv", "text/csv")

st.markdown("---")
st.caption("💡 Tips: tambah kata kunci spesifik seperti 'DPRD', 'Polda', 'Polres', 'Gedung DPR', 'Senayan', 'Affan'.")
