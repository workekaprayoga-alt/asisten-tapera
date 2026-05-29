import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import json
import os
from datetime import datetime

# ============================================================
# KONFIGURASI — isi di sini atau pakai .env / Streamlit Secrets
# ============================================================
SUPABASE_URL  = st.secrets.get("SUPABASE_URL",  "https://wsknzpurkujhyzdoiffh.supabase.co")
SUPABASE_KEY  = st.secrets.get("SUPABASE_KEY",  "")   # sb_secret_...
DEEPSEEK_KEY  = st.secrets.get("DEEPSEEK_KEY",  "")   # sk-...
TABLE_NAME    = "realisasi"

# ============================================================
# SETUP HALAMAN
# ============================================================
st.set_page_config(
    page_title="Asisten AI Data Tapera FLPP",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CSS KUSTOM
# ============================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f2027 100%);
    }
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 4px 24px rgba(0,0,0,0.3);
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-label {
        color: #94a3b8;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .metric-value {
        color: #38bdf8;
        font-size: 28px;
        font-weight: 800;
        line-height: 1.1;
    }
    .metric-sub {
        color: #64748b;
        font-size: 11px;
        margin-top: 4px;
    }
    .chat-user {
        background: linear-gradient(135deg, #1d4ed8, #3b82f6);
        border-radius: 16px 16px 4px 16px;
        padding: 14px 18px;
        margin: 8px 0;
        max-width: 80%;
        margin-left: auto;
        color: white;
        font-size: 14px;
    }
    .chat-ai {
        background: linear-gradient(135deg, #1e293b, #1e3a5f);
        border: 1px solid #334155;
        border-radius: 16px 16px 16px 4px;
        padding: 14px 18px;
        margin: 8px 0;
        max-width: 95%;
        color: #e2e8f0;
        font-size: 14px;
    }
    .section-header {
        color: #38bdf8;
        font-size: 18px;
        font-weight: 700;
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 2px solid #1e3a5f;
    }
    div[data-testid="stTabs"] button {
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 600 !important;
        font-size: 13px !important;
    }
    .stButton > button {
        background: linear-gradient(135deg, #1d4ed8, #3b82f6) !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        background: #1e293b !important;
        border: 1px solid #334155 !important;
        color: #e2e8f0 !important;
        border-radius: 8px !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }
    .stSelectbox > div > div {
        background: #1e293b !important;
        border: 1px solid #334155 !important;
        color: #e2e8f0 !important;
    }
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
        background: #0f172a !important;
        color: #7dd3fc !important;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# HELPER — SUPABASE REST API
# ============================================================
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

@st.cache_data(ttl=300)
def query_supabase(select: str = "*", filters: dict = None,
                   order: str = None, limit: int = 1000) -> pd.DataFrame:
    """Ambil data dari Supabase dengan filter opsional."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    params = {"select": select}
    if filters:
        params.update(filters)
    if order:
        params["order"] = order
    if limit:
        params["limit"] = limit

    try:
        r = requests.get(url, headers=sb_headers(), params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Gagal ambil data Supabase: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def query_supabase_rpc(func_name: str, params: dict = None) -> dict:
    """Panggil Supabase RPC function."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/{func_name}"
    try:
        r = requests.post(url, headers=sb_headers(),
                          json=params or {}, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def count_all() -> int:
    """Hitung total baris di tabel."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    h["Prefer"] = "count=exact"
    try:
        r = requests.get(url, headers=h,
                         params={"select": "id", "limit": "1"}, timeout=15)
        ct = r.headers.get("content-range", "0/0")
        total = int(ct.split("/")[-1]) if "/" in ct else 0
        return total
    except:
        return 0

# ============================================================
# HELPER — DEEPSEEK AI
# ============================================================
def tanya_deepseek(prompt: str, system: str = "") -> str:
    """Kirim pertanyaan ke DeepSeek API."""
    if not DEEPSEEK_KEY:
        return "⚠️ DEEPSEEK_KEY belum diisi di Streamlit Secrets."

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1500,
    }
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers, json=body, timeout=60
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Error DeepSeek: {e}"

def nl_to_supabase_filter(pertanyaan: str, sample_cols: list) -> dict:
    """Minta DeepSeek translate pertanyaan ke Supabase filter params."""
    system = f"""Kamu adalah asisten yang mengubah pertanyaan bahasa Indonesia menjadi filter Supabase REST API.
Kolom yang tersedia: {', '.join(sample_cols)}.
Format output HANYA JSON tanpa komentar, contoh:
{{"select": "provinsi,jumlah_unit,nilai_kredit", "provinsi": "eq.JAWA BARAT", "order": "jumlah_unit.desc", "limit": 20}}
Jika pertanyaan butuh agregasi (SUM, COUNT, GROUP BY), kembalikan:
{{"mode": "ai_compute", "select": "*", "limit": 5000}}
Jangan tambahkan penjelasan apapun di luar JSON."""

    raw = tanya_deepseek(pertanyaan, system)
    # Bersihkan markdown code block kalau ada
    raw = raw.strip().strip("```json").strip("```").strip()
    try:
        return json.loads(raw)
    except:
        return {"select": "*", "limit": 500}

# ============================================================
# PLOT HELPERS
# ============================================================
PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15,23,42,0.8)",
    font=dict(family="Plus Jakarta Sans", color="#94a3b8", size=12),
    title_font=dict(color="#e2e8f0", size=14),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
    margin=dict(t=40, b=30, l=10, r=10),
)
COLORS = ["#38bdf8", "#818cf8", "#34d399", "#fb923c",
          "#f472b6", "#a3e635", "#facc15", "#60a5fa"]

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## 🏠 Tapera FLPP")
    st.markdown("**Asisten AI Data Perumahan**")
    st.divider()

    # Status koneksi
    if SUPABASE_KEY:
        total = count_all()
        if total > 0:
            st.success(f"✅ Supabase terhubung\n\n**{total:,}** total baris")
        else:
            st.warning(f"⚠️ Supabase terhubung tapi tabel `{TABLE_NAME}` kosong atau tidak ditemukan")
            # Coba cek tabel lain
            try:
                r2 = requests.get(
                    f"{SUPABASE_URL}/rest/v1/",
                    headers=sb_headers(), timeout=10
                )
                st.caption(f"Status: {r2.status_code}")
            except Exception as e:
                st.caption(f"Error: {e}")
    else:
        st.error("❌ SUPABASE_KEY belum diisi")

    if DEEPSEEK_KEY:
        st.success("✅ DeepSeek AI siap")
    else:
        st.warning("⚠️ DEEPSEEK_KEY belum diisi")

    st.divider()
    st.caption("Filter Global")
    tahun_filter = st.selectbox(
        "Tahun", ["Semua", "2020", "2021", "2022", "2023", "2024"],
        index=0
    )
    st.caption("💡 Filter berlaku di semua tab")
    st.divider()
    st.caption("v1.0 · Streamlit Cloud · DeepSeek AI")

# ============================================================
# TABS UTAMA
# ============================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Dashboard",
    "🤖 Tanya AI",
    "🗺️ Analisis Daerah",
    "🏗️ Pengembang",
    "🏦 Bank & Pembiayaan",
    "👥 Profil Pembeli",
])

# ------------------------------------------------------------------
# TAB 1 — DASHBOARD NASIONAL
# ------------------------------------------------------------------
with tab1:
    st.markdown('<div class="section-header">📊 Dashboard Nasional FLPP</div>',
                unsafe_allow_html=True)

    # Deteksi kolom yang tersedia
    df_sample = query_supabase(select="*", limit=10)
    if df_sample.empty:
        st.info("⏳ Menunggu koneksi Supabase atau data belum tersedia.")
    else:
        cols = df_sample.columns.tolist()
        st.caption(f"Kolom tersedia: `{'`, `'.join(cols)}`")

        # Deteksi nama kolom otomatis (toleran terhadap variasi)
        def col(candidates):
            for c in candidates:
                if c in cols: return c
            return None

        c_prov    = col(["provinsi", "PROVINSI", "province"])
        c_kab     = col(["kabupaten", "KABUPATEN", "kota", "KOTA"])
        c_unit    = col(["jumlah_unit", "unit", "UNIT", "jumlah_realisasi"])
        c_nilai   = col(["nilai_kredit", "nilai", "NILAI", "kredit"])
        c_bank    = col(["bank_pelaksana", "bank", "BANK"])
        c_dev     = col(["nama_pengembang", "pengembang", "PENGEMBANG", "developer"])
        c_tahun   = col(["tahun", "TAHUN", "year"])
        c_gender  = col(["jenis_kelamin", "gender", "GENDER"])
        c_profesi = col(["profesi", "PROFESI", "pekerjaan"])
        c_tenor   = col(["tenor", "TENOR"])
        c_harga   = col(["harga_rumah", "harga", "HARGA"])
        c_peng    = col(["penghasilan", "PENGHASILAN", "income"])

        # Ambil data besar untuk dashboard
        f = {}
        if tahun_filter != "Semua" and c_tahun:
            f[c_tahun] = f"eq.{tahun_filter}"

        df = query_supabase(select="*", filters=f, limit=10000)

        if not df.empty and c_unit:
            df[c_unit] = pd.to_numeric(df[c_unit], errors="coerce").fillna(0)
        if not df.empty and c_nilai:
            df[c_nilai] = pd.to_numeric(df[c_nilai], errors="coerce").fillna(0)

        # KPI CARDS
        if not df.empty:
            k1, k2, k3, k4 = st.columns(4)

            total_unit  = int(df[c_unit].sum())  if c_unit  else 0
            total_nilai = df[c_nilai].sum()       if c_nilai else 0
            total_prov  = df[c_prov].nunique()    if c_prov  else 0
            total_bank  = df[c_bank].nunique()    if c_bank  else 0

            with k1:
                st.markdown(f"""<div class="metric-card">
                    <div class="metric-label">Total Unit FLPP</div>
                    <div class="metric-value">{total_unit:,}</div>
                    <div class="metric-sub">Unit rumah dibiayai</div>
                </div>""", unsafe_allow_html=True)

            with k2:
                val_t = total_nilai / 1e12
                st.markdown(f"""<div class="metric-card">
                    <div class="metric-label">Total Nilai Kredit</div>
                    <div class="metric-value">Rp {val_t:.1f}T</div>
                    <div class="metric-sub">Triliun rupiah</div>
                </div>""", unsafe_allow_html=True)

            with k3:
                st.markdown(f"""<div class="metric-card">
                    <div class="metric-label">Provinsi Aktif</div>
                    <div class="metric-value">{total_prov}</div>
                    <div class="metric-sub">Dari 38 provinsi</div>
                </div>""", unsafe_allow_html=True)

            with k4:
                st.markdown(f"""<div class="metric-card">
                    <div class="metric-label">Bank Pelaksana</div>
                    <div class="metric-value">{total_bank}</div>
                    <div class="metric-sub">Bank aktif FLPP</div>
                </div>""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # GRAFIK BARIS 1
            col_a, col_b = st.columns(2)

            with col_a:
                if c_prov and c_unit:
                    top_prov = (df.groupby(c_prov)[c_unit]
                                .sum().nlargest(10).reset_index())
                    top_prov.columns = ["Provinsi", "Unit"]
                    fig = px.bar(top_prov, x="Unit", y="Provinsi",
                                 orientation="h",
                                 title="🏆 Top 10 Provinsi",
                                 color="Unit",
                                 color_continuous_scale="Blues")
                    fig.update_layout(**PLOT_LAYOUT)
                    fig.update_coloraxes(showscale=False)
                    st.plotly_chart(fig, use_container_width=True)

            with col_b:
                if c_bank and c_unit:
                    bank_share = (df.groupby(c_bank)[c_unit]
                                  .sum().nlargest(8).reset_index())
                    bank_share.columns = ["Bank", "Unit"]
                    fig = px.pie(bank_share, values="Unit", names="Bank",
                                 title="🏦 Market Share Bank",
                                 color_discrete_sequence=COLORS,
                                 hole=0.4)
                    fig.update_layout(**PLOT_LAYOUT)
                    st.plotly_chart(fig, use_container_width=True)

            # GRAFIK BARIS 2
            col_c, col_d = st.columns(2)

            with col_c:
                if c_tahun and c_unit:
                    tren = (df.groupby(c_tahun)[c_unit]
                            .sum().reset_index())
                    tren.columns = ["Tahun", "Unit"]
                    tren = tren.sort_values("Tahun")
                    fig = px.line(tren, x="Tahun", y="Unit",
                                  title="📈 Tren Tahunan",
                                  markers=True,
                                  color_discrete_sequence=["#38bdf8"])
                    fig.update_traces(line_width=3, marker_size=8)
                    fig.update_layout(**PLOT_LAYOUT)
                    st.plotly_chart(fig, use_container_width=True)

            with col_d:
                if c_dev and c_unit:
                    top_dev = (df.groupby(c_dev)[c_unit]
                               .sum().nlargest(10).reset_index())
                    top_dev.columns = ["Pengembang", "Unit"]
                    fig = px.bar(top_dev, x="Pengembang", y="Unit",
                                 title="🏗️ Top 10 Pengembang",
                                 color_discrete_sequence=["#818cf8"])
                    fig.update_layout(**PLOT_LAYOUT)
                    fig.update_xaxes(tickangle=45)
                    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# TAB 2 — TANYA AI
# ------------------------------------------------------------------
with tab2:
    st.markdown('<div class="section-header">🤖 Tanya AI tentang Data Tapera</div>',
                unsafe_allow_html=True)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Tampilkan riwayat chat
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-user">👤 {msg["content"]}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-ai">🤖 {msg["content"]}</div>',
                        unsafe_allow_html=True)

    # Input pertanyaan
    pertanyaan = st.text_area(
        "Ajukan pertanyaan tentang data FLPP:",
        placeholder="Contoh: Provinsi mana yang paling banyak unit FLPP? / Siapa top 5 pengembang di Jawa Barat? / Tren unit di 2023?",
        height=100,
        key="input_chat"
    )

    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        kirim = st.button("✉️ Kirim", use_container_width=True)
    with col_btn2:
        if st.button("🗑️ Hapus Riwayat"):
            st.session_state.chat_history = []
            st.rerun()

    if kirim and pertanyaan.strip():
        st.session_state.chat_history.append(
            {"role": "user", "content": pertanyaan}
        )

        with st.spinner("🔍 Mengambil data & menganalisis..."):
            # Deteksi kolom dari sample
            df_s = query_supabase(select="*", limit=5)
            sample_cols = df_s.columns.tolist() if not df_s.empty else []

            # Minta AI buat filter
            filter_params = nl_to_supabase_filter(pertanyaan, sample_cols)
            mode = filter_params.pop("mode", "direct")

            # Ambil data
            df_result = query_supabase(**{
                k: v for k, v in filter_params.items()
                if k in ["select", "order", "limit"]
            })
            # Terapkan filter equality
            extra_filters = {k: v for k, v in filter_params.items()
                             if k not in ["select", "order", "limit"]}
            if extra_filters and not df_result.empty:
                df_result = query_supabase(
                    select=filter_params.get("select", "*"),
                    filters=extra_filters,
                    order=filter_params.get("order"),
                    limit=int(filter_params.get("limit", 500))
                )

            if df_result.empty:
                jawaban = "Tidak ditemukan data yang sesuai dengan pertanyaan kamu."
            else:
                # Minta AI analisis
                data_preview = df_result.head(50).to_csv(index=False)
                system_analisis = """Kamu adalah analis data FLPP (Fasilitas Likuiditas Pembiayaan Perumahan) Tapera yang ahli.
Jawab pertanyaan berdasarkan data yang diberikan dalam bahasa Indonesia yang jelas dan informatif.
Sertakan insight penting, angka-angka kunci, dan kesimpulan yang actionable.
Gunakan emoji untuk memperjelas. Jangan sebut 'CSV' atau detail teknis."""

                prompt_analisis = f"""Pertanyaan: {pertanyaan}

Data (preview {min(50, len(df_result))} dari {len(df_result)} baris):
{data_preview}

Analisis dan jawab pertanyaan di atas berdasarkan data ini."""

                jawaban = tanya_deepseek(prompt_analisis, system_analisis)

                # Tampilkan tabel kalau tidak terlalu besar
                if len(df_result) <= 200:
                    st.dataframe(
                        df_result,
                        use_container_width=True,
                        height=300
                    )

        st.session_state.chat_history.append(
            {"role": "assistant", "content": jawaban}
        )
        st.rerun()

# ------------------------------------------------------------------
# TAB 3 — ANALISIS DAERAH
# ------------------------------------------------------------------
with tab3:
    st.markdown('<div class="section-header">🗺️ Analisis Per Daerah</div>',
                unsafe_allow_html=True)

    df_prov_list = query_supabase(select="provinsi", limit=50000)
    if df_prov_list.empty or "provinsi" not in df_prov_list.columns:
        st.info("⏳ Data belum tersedia. Pastikan upload sudah selesai.")
    else:
        prov_list = sorted(df_prov_list["provinsi"].dropna().unique().tolist())
        selected_prov = st.selectbox("Pilih Provinsi:", prov_list)

        if selected_prov:
            df_prov = query_supabase(
                select="*",
                filters={"provinsi": f"eq.{selected_prov}"},
                limit=10000
            )

            if not df_prov.empty:
                cols = df_prov.columns.tolist()

                # KPI Provinsi
                c_unit  = next((c for c in ["jumlah_unit","unit","UNIT"] if c in cols), None)
                c_nilai = next((c for c in ["nilai_kredit","nilai","NILAI"] if c in cols), None)
                c_kab   = next((c for c in ["kabupaten","KABUPATEN","kota","KOTA"] if c in cols), None)
                c_dev   = next((c for c in ["nama_pengembang","pengembang","PENGEMBANG"] if c in cols), None)

                if c_unit:
                    df_prov[c_unit] = pd.to_numeric(df_prov[c_unit], errors="coerce").fillna(0)
                if c_nilai:
                    df_prov[c_nilai] = pd.to_numeric(df_prov[c_nilai], errors="coerce").fillna(0)

                m1, m2, m3 = st.columns(3)
                with m1:
                    v = int(df_prov[c_unit].sum()) if c_unit else 0
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Total Unit</div><div class="metric-value">{v:,}</div></div>',
                                unsafe_allow_html=True)
                with m2:
                    v = df_prov[c_nilai].sum() / 1e9 if c_nilai else 0
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Nilai Kredit</div><div class="metric-value">Rp {v:.1f}M</div><div class="metric-sub">Miliar</div></div>',
                                unsafe_allow_html=True)
                with m3:
                    v = df_prov[c_kab].nunique() if c_kab else 0
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Kab/Kota</div><div class="metric-value">{v}</div></div>',
                                unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                col_x, col_y = st.columns(2)

                with col_x:
                    if c_kab and c_unit:
                        top_kab = df_prov.groupby(c_kab)[c_unit].sum().nlargest(10).reset_index()
                        top_kab.columns = ["Kab/Kota", "Unit"]
                        fig = px.bar(top_kab, x="Unit", y="Kab/Kota",
                                     orientation="h",
                                     title=f"Top 10 Kab/Kota — {selected_prov}",
                                     color_discrete_sequence=["#34d399"])
                        fig.update_layout(**PLOT_LAYOUT)
                        st.plotly_chart(fig, use_container_width=True)

                with col_y:
                    if c_dev and c_unit:
                        top_dev_prov = df_prov.groupby(c_dev)[c_unit].sum().nlargest(10).reset_index()
                        top_dev_prov.columns = ["Pengembang", "Unit"]
                        fig = px.bar(top_dev_prov, x="Pengembang", y="Unit",
                                     title=f"Top 10 Pengembang — {selected_prov}",
                                     color_discrete_sequence=["#fb923c"])
                        fig.update_layout(**PLOT_LAYOUT)
                        fig.update_xaxes(tickangle=45)
                        st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# TAB 4 — PENGEMBANG
# ------------------------------------------------------------------
with tab4:
    st.markdown('<div class="section-header">🏗️ Analisis Pengembang</div>',
                unsafe_allow_html=True)

    df_dev_raw = query_supabase(select="*", limit=10000)
    if df_dev_raw.empty:
        st.info("⏳ Menunggu data...")
    else:
        cols = df_dev_raw.columns.tolist()
        c_dev  = next((c for c in ["nama_pengembang","pengembang","PENGEMBANG"] if c in cols), None)
        c_unit = next((c for c in ["jumlah_unit","unit","UNIT"] if c in cols), None)
        c_prov = next((c for c in ["provinsi","PROVINSI"] if c in cols), None)

        if c_dev and c_unit:
            df_dev_raw[c_unit] = pd.to_numeric(df_dev_raw[c_unit], errors="coerce").fillna(0)

            # Search
            keyword = st.text_input("🔍 Cari nama pengembang:", placeholder="Contoh: GRAHA, CIPUTRA, PERUMNAS...")

            top_dev = df_dev_raw.groupby(c_dev)[c_unit].sum().nlargest(20).reset_index()
            top_dev.columns = ["Pengembang", "Unit"]

            if keyword:
                top_dev = top_dev[top_dev["Pengembang"].str.contains(keyword, case=False, na=False)]

            fig = px.bar(top_dev, x="Pengembang", y="Unit",
                         title="Top 20 Pengembang Nasional",
                         color="Unit",
                         color_continuous_scale="Viridis")
            fig.update_layout(**PLOT_LAYOUT)
            fig.update_xaxes(tickangle=45)
            fig.update_coloraxes(showscale=False)
            st.plotly_chart(fig, use_container_width=True)

            # White spot analysis
            st.markdown('<div class="section-header">⬜ White Spot Analysis</div>',
                        unsafe_allow_html=True)
            st.caption("Provinsi dengan sedikit pengembang aktif — peluang pasar!")

            if c_prov:
                dev_per_prov = (df_dev_raw.groupby(c_prov)[c_dev]
                                .nunique().reset_index())
                dev_per_prov.columns = ["Provinsi", "Jumlah Pengembang"]
                dev_per_prov = dev_per_prov.sort_values("Jumlah Pengembang")

                fig2 = px.bar(dev_per_prov, x="Jumlah Pengembang", y="Provinsi",
                              orientation="h",
                              title="Jumlah Pengembang per Provinsi",
                              color="Jumlah Pengembang",
                              color_continuous_scale="RdYlGn")
                fig2.update_layout(**PLOT_LAYOUT)
                fig2.update_coloraxes(showscale=False)
                st.plotly_chart(fig2, use_container_width=True)

# ------------------------------------------------------------------
# TAB 5 — BANK & PEMBIAYAAN
# ------------------------------------------------------------------
with tab5:
    st.markdown('<div class="section-header">🏦 Analisis Bank & Pembiayaan</div>',
                unsafe_allow_html=True)

    df_bank_raw = query_supabase(select="*", limit=10000)
    if df_bank_raw.empty:
        st.info("⏳ Menunggu data...")
    else:
        cols = df_bank_raw.columns.tolist()
        c_bank  = next((c for c in ["bank_pelaksana","bank","BANK"] if c in cols), None)
        c_unit  = next((c for c in ["jumlah_unit","unit","UNIT"] if c in cols), None)
        c_nilai = next((c for c in ["nilai_kredit","nilai","NILAI"] if c in cols), None)
        c_prov  = next((c for c in ["provinsi","PROVINSI"] if c in cols), None)

        if c_bank and c_unit:
            df_bank_raw[c_unit] = pd.to_numeric(df_bank_raw[c_unit], errors="coerce").fillna(0)
            if c_nilai:
                df_bank_raw[c_nilai] = pd.to_numeric(df_bank_raw[c_nilai], errors="coerce").fillna(0)

            col_a, col_b = st.columns(2)

            with col_a:
                share = df_bank_raw.groupby(c_bank)[c_unit].sum().nlargest(8).reset_index()
                share.columns = ["Bank", "Unit"]
                fig = px.pie(share, values="Unit", names="Bank",
                             title="Market Share Unit FLPP per Bank",
                             color_discrete_sequence=COLORS, hole=0.35)
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)

            with col_b:
                if c_nilai:
                    nilai_bank = df_bank_raw.groupby(c_bank)[c_nilai].sum().nlargest(8).reset_index()
                    nilai_bank.columns = ["Bank", "Nilai"]
                    nilai_bank["Nilai_T"] = nilai_bank["Nilai"] / 1e12
                    fig = px.bar(nilai_bank, x="Bank", y="Nilai_T",
                                 title="Nilai Kredit per Bank (Triliun Rp)",
                                 color_discrete_sequence=["#38bdf8"])
                    fig.update_layout(**PLOT_LAYOUT)
                    fig.update_xaxes(tickangle=30)
                    st.plotly_chart(fig, use_container_width=True)

            # Bank dominan per provinsi
            if c_prov:
                st.markdown('<div class="section-header">🗺️ Bank Dominan per Provinsi</div>',
                            unsafe_allow_html=True)
                dom = (df_bank_raw.groupby([c_prov, c_bank])[c_unit]
                       .sum().reset_index())
                dom_idx = dom.groupby(c_prov)[c_unit].idxmax()
                dom_bank = dom.loc[dom_idx, [c_prov, c_bank, c_unit]]
                dom_bank.columns = ["Provinsi", "Bank Dominan", "Unit"]
                dom_bank = dom_bank.sort_values("Unit", ascending=False)
                st.dataframe(dom_bank, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# TAB 6 — PROFIL PEMBELI
# ------------------------------------------------------------------
with tab6:
    st.markdown('<div class="section-header">👥 Profil Pembeli FLPP</div>',
                unsafe_allow_html=True)

    df_profil = query_supabase(select="*", limit=10000)
    if df_profil.empty:
        st.info("⏳ Menunggu data...")
    else:
        cols = df_profil.columns.tolist()

        def find_col(candidates):
            for c in candidates:
                if c in cols: return c
            return None

        c_gender  = find_col(["jenis_kelamin","gender","GENDER"])
        c_profesi = find_col(["profesi","PROFESI","pekerjaan","PEKERJAAN"])
        c_tenor   = find_col(["tenor","TENOR"])
        c_harga   = find_col(["harga_rumah","harga","HARGA"])
        c_peng    = find_col(["penghasilan","PENGHASILAN","income"])
        c_unit    = find_col(["jumlah_unit","unit","UNIT"])

        row1_a, row1_b = st.columns(2)

        with row1_a:
            if c_gender and c_unit:
                df_profil[c_unit] = pd.to_numeric(df_profil[c_unit], errors="coerce").fillna(0)
                gender_data = df_profil.groupby(c_gender)[c_unit].sum().reset_index()
                gender_data.columns = ["Jenis Kelamin", "Unit"]
                fig = px.pie(gender_data, values="Unit", names="Jenis Kelamin",
                             title="Distribusi Jenis Kelamin",
                             color_discrete_sequence=["#38bdf8", "#f472b6"],
                             hole=0.4)
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom jenis_kelamin/unit tidak ditemukan")

        with row1_b:
            if c_profesi and c_unit:
                profesi_data = df_profil.groupby(c_profesi)[c_unit].sum().nlargest(8).reset_index()
                profesi_data.columns = ["Profesi", "Unit"]
                fig = px.bar(profesi_data, x="Unit", y="Profesi",
                             orientation="h",
                             title="Top Profesi Pembeli",
                             color_discrete_sequence=["#34d399"])
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom profesi/unit tidak ditemukan")

        row2_a, row2_b = st.columns(2)

        with row2_a:
            if c_tenor and c_unit:
                tenor_data = df_profil.groupby(c_tenor)[c_unit].sum().reset_index()
                tenor_data.columns = ["Tenor (Tahun)", "Unit"]
                fig = px.bar(tenor_data, x="Tenor (Tahun)", y="Unit",
                             title="Distribusi Tenor KPR",
                             color_discrete_sequence=["#818cf8"])
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom tenor tidak ditemukan")

        with row2_b:
            if c_harga:
                df_profil[c_harga] = pd.to_numeric(df_profil[c_harga], errors="coerce")
                fig = px.histogram(df_profil.dropna(subset=[c_harga]),
                                   x=c_harga,
                                   title="Distribusi Harga Rumah",
                                   color_discrete_sequence=["#fb923c"],
                                   nbins=30)
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom harga_rumah tidak ditemukan")
