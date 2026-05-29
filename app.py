import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import json

# ============================================================
# KONFIGURASI
# ============================================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://wsknzpurkujhyzdoiffh.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
ANTHROPIC_KEY = st.secrets.get("ANTHROPIC_KEY", "")   # Claude AI (ganti DeepSeek)
DEEPSEEK_KEY  = st.secrets.get("DEEPSEEK_KEY", "")    # Fallback
TABLE_NAME = "realisasi"

# ============================================================
# SETUP HALAMAN
# ============================================================
st.set_page_config(
    page_title="Asisten AI Data Tapera FLPP",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
    html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; }
    .stApp { background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f2027 100%); }
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border: 1px solid #334155; border-radius: 12px; padding: 20px;
        text-align: center; box-shadow: 0 4px 24px rgba(0,0,0,0.3); transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-label { color: #94a3b8; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
    .metric-value { color: #38bdf8; font-size: 28px; font-weight: 800; line-height: 1.1; }
    .metric-sub { color: #64748b; font-size: 11px; margin-top: 4px; }
    .chat-user {
        background: linear-gradient(135deg, #1d4ed8, #3b82f6);
        border-radius: 16px 16px 4px 16px; padding: 14px 18px;
        margin: 8px 0; max-width: 80%; margin-left: auto; color: white; font-size: 14px;
    }
    .chat-ai {
        background: linear-gradient(135deg, #1e293b, #1e3a5f);
        border: 1px solid #334155; border-radius: 16px 16px 16px 4px;
        padding: 14px 18px; margin: 8px 0; max-width: 95%; color: #e2e8f0; font-size: 14px;
    }
    .section-header {
        color: #38bdf8; font-size: 18px; font-weight: 700;
        margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #1e3a5f;
    }
    div[data-testid="stTabs"] button { font-family: 'Plus Jakarta Sans', sans-serif !important; font-weight: 600 !important; font-size: 13px !important; }
    .stButton > button { background: linear-gradient(135deg, #1d4ed8, #3b82f6) !important; color: white !important; border: none !important; border-radius: 8px !important; font-weight: 600 !important; }
    .stTextInput > div > div > input, .stTextArea > div > div > textarea { background: #1e293b !important; border: 1px solid #334155 !important; color: #e2e8f0 !important; border-radius: 8px !important; }
    .stSelectbox > div > div { background: #1e293b !important; border: 1px solid #334155 !important; color: #e2e8f0 !important; }
    code, pre { font-family: 'JetBrains Mono', monospace !important; background: #0f172a !important; color: #7dd3fc !important; }
</style>
""", unsafe_allow_html=True)

PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15,23,42,0.8)",
    font=dict(family="Plus Jakarta Sans", color="#94a3b8", size=12),
    title_font=dict(color="#e2e8f0", size=14),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
    margin=dict(t=40, b=30, l=10, r=10),
)
COLORS = ["#38bdf8","#818cf8","#34d399","#fb923c","#f472b6","#a3e635","#facc15","#60a5fa"]

# ============================================================
# SUPABASE HELPERS
# ============================================================
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

@st.cache_data(ttl=300)
def query_supabase(select="*", filters=None, order=None, limit=1000):
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    params = {"select": select}
    if filters: params.update(filters)
    if order: params["order"] = order
    if limit: params["limit"] = limit
    try:
        r = requests.get(url, headers=sb_headers(), params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Gagal ambil data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def count_all():
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    h["Prefer"] = "count=exact"
    try:
        r = requests.get(url, headers=h, params={"select": "id", "limit": "1"}, timeout=15)
        ct = r.headers.get("content-range", "0/0")
        return int(ct.split("/")[-1]) if "/" in ct else 0
    except:
        return 0

# ============================================================
# MAPPING KOLOM — sesuai data nyata
# Kolom asli: id, tahun_akad, tahun_realisasi, bank, asosiasi, jenis_rumah,
#             provinsi, kabupaten, kecamatan, kelurahan, kelamin, pekerjaan,
#             penghasilan, nama_pengembang, nama_perumahan, luas_bangunan,
#             luas_tanah, harga_rumah, tenor, suku_bunga_kpr, nilai_flpp,
#             tgl_akad, tanggal_pencairan
# ============================================================
def detect_cols(cols):
    def find(candidates):
        for c in candidates:
            if c in cols: return c
        return None
    return {
        "prov":   find(["provinsi", "PROVINSI", "province"]),
        "kab":    find(["kabupaten", "KABUPATEN", "kota", "KOTA"]),
        "unit":   None,   # tidak ada kolom unit, pakai COUNT = len(df)
        "nilai":  find(["nilai_flpp", "nilai_kredit", "nilai", "NILAI"]),
        "bank":   find(["bank", "bank_pelaksana", "BANK"]),
        "dev":    find(["nama_pengembang", "pengembang", "PENGEMBANG"]),
        "tahun":  find(["tahun_akad", "tahun_realisasi", "tahun", "TAHUN"]),
        "gender": find(["kelamin", "jenis_kelamin", "gender", "GENDER"]),
        "profesi":find(["pekerjaan", "profesi", "PROFESI"]),
        "tenor":  find(["tenor", "TENOR"]),
        "harga":  find(["harga_rumah", "harga", "HARGA"]),
        "peng":   find(["penghasilan", "PENGHASILAN", "income"]),
    }

def count_by(df, group_col):
    """Hitung jumlah baris per group (karena tidak ada kolom jumlah_unit)."""
    return df.groupby(group_col).size().reset_index(name="Unit")

def count_by_nlargest(df, group_col, n=10):
    return count_by(df, group_col).nlargest(n, "Unit")

# ============================================================
# AI HELPER — Claude Anthropic (primer) atau DeepSeek (fallback)
# ============================================================
def tanya_ai(prompt, system=""):
    # Coba Anthropic Claude dulu
    if ANTHROPIC_KEY:
        headers = {
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        msgs = []
        if system:
            # Anthropic pakai system param terpisah
            pass
        msgs.append({"role": "user", "content": prompt})
        body = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1500,
            "system": system if system else "Kamu adalah analis data FLPP Tapera.",
            "messages": msgs,
        }
        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                              headers=headers, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        except Exception as e:
            # Fallback ke DeepSeek
            pass

    # Fallback DeepSeek
    if DEEPSEEK_KEY:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        }
        messages = []
        if system: messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {"model": "deepseek-chat", "messages": messages, "temperature": 0.3, "max_tokens": 1500}
        try:
            r = requests.post("https://api.deepseek.com/chat/completions",
                              headers=headers, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"❌ Error AI: {e}"

    return "⚠️ API Key AI belum diisi. Tambahkan ANTHROPIC_KEY atau DEEPSEEK_KEY di Streamlit Secrets."

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## 🏠 Tapera FLPP")
    st.markdown("**Asisten AI Data Perumahan**")
    st.divider()

    if SUPABASE_KEY:
        total = count_all()
        if total > 0:
            st.success(f"✅ Supabase terhubung\n\n**{total:,}** total baris")
        else:
            st.warning(f"⚠️ Tabel `{TABLE_NAME}` kosong")
    else:
        st.error("❌ SUPABASE_KEY belum diisi")

    if ANTHROPIC_KEY:
        st.success("✅ Claude AI siap")
    elif DEEPSEEK_KEY:
        st.success("✅ DeepSeek AI siap")
    else:
        st.warning("⚠️ Tambahkan ANTHROPIC_KEY di Secrets")

    st.divider()
    st.caption("Filter Global")

    # Ambil tahun dari data nyata (tahun_akad)
    @st.cache_data(ttl=300)
    def get_tahun_list():
        df_t = query_supabase(select="tahun_akad", limit=100000)
        if not df_t.empty and "tahun_akad" in df_t.columns:
            tahun = sorted(df_t["tahun_akad"].dropna().unique().tolist(), reverse=True)
            return [str(int(t)) for t in tahun if str(t).isdigit() or isinstance(t, (int, float))]
        return []

    tahun_options = ["Semua"] + get_tahun_list()
    tahun_filter = st.selectbox("Tahun", tahun_options, index=0)
    st.caption("💡 Filter berlaku di semua tab")
    st.divider()

    ai_label = "Claude AI" if ANTHROPIC_KEY else ("DeepSeek" if DEEPSEEK_KEY else "Tidak ada AI")
    st.caption(f"v2.0 · {ai_label} · Streamlit Cloud")

# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Dashboard",
    "🤖 Tanya AI",
    "🗺️ Analisis Daerah",
    "🏗️ Pengembang",
    "🏦 Bank & Pembiayaan",
    "👥 Profil Pembeli",
])

# ---------------------------------------------------------------
# TAB 1 — DASHBOARD NASIONAL
# ---------------------------------------------------------------
with tab1:
    st.markdown('<div class="section-header">📊 Dashboard Nasional FLPP</div>', unsafe_allow_html=True)

    df_sample = query_supabase(select="*", limit=10)
    if df_sample.empty:
        st.info("⏳ Menunggu koneksi Supabase.")
    else:
        cols = df_sample.columns.tolist()
        st.caption(f"Kolom tersedia: `{'`, `'.join(cols)}`")
        cm = detect_cols(cols)

        # Ambil data dengan filter tahun jika dipilih
        f = {}
        if tahun_filter != "Semua" and cm["tahun"]:
            f[cm["tahun"]] = f"eq.{tahun_filter}"

        df = query_supabase(select="*", filters=f, limit=10000)

        if not df.empty:
            # Konversi numerik
            for key in ["nilai", "harga", "peng", "tenor"]:
                if cm[key] and cm[key] in df.columns:
                    df[cm[key]] = pd.to_numeric(df[cm[key]], errors="coerce").fillna(0)

            # KPI
            total_unit  = len(df)
            total_nilai = df[cm["nilai"]].sum() if cm["nilai"] else 0
            total_prov  = df[cm["prov"]].nunique() if cm["prov"] else 0
            total_bank  = df[cm["bank"]].nunique() if cm["bank"] else 0

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Total Unit FLPP</div><div class="metric-value">{total_unit:,}</div><div class="metric-sub">Unit rumah dibiayai (sampel)</div></div>', unsafe_allow_html=True)
            with k2:
                val_t = total_nilai / 1e12
                st.markdown(f'<div class="metric-card"><div class="metric-label">Total Nilai FLPP</div><div class="metric-value">Rp {val_t:.1f}T</div><div class="metric-sub">Triliun rupiah</div></div>', unsafe_allow_html=True)
            with k3:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Provinsi Aktif</div><div class="metric-value">{total_prov}</div><div class="metric-sub">Dari 38 provinsi</div></div>', unsafe_allow_html=True)
            with k4:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Bank Pelaksana</div><div class="metric-value">{total_bank}</div><div class="metric-sub">Bank aktif FLPP</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            col_a, col_b = st.columns(2)

            with col_a:
                if cm["prov"]:
                    top_prov = count_by_nlargest(df, cm["prov"], 10)
                    fig = px.bar(top_prov, x="Unit", y=cm["prov"], orientation="h",
                                 title="🏆 Top 10 Provinsi", color="Unit",
                                 color_continuous_scale="Blues",
                                 labels={cm["prov"]: "Provinsi"})
                    fig.update_layout(**PLOT_LAYOUT)
                    fig.update_coloraxes(showscale=False)
                    st.plotly_chart(fig, use_container_width=True)

            with col_b:
                if cm["bank"]:
                    bank_share = count_by_nlargest(df, cm["bank"], 8)
                    fig = px.pie(bank_share, values="Unit", names=cm["bank"],
                                 title="🏦 Market Share Bank",
                                 color_discrete_sequence=COLORS, hole=0.4)
                    fig.update_layout(**PLOT_LAYOUT)
                    st.plotly_chart(fig, use_container_width=True)

            col_c, col_d = st.columns(2)
            with col_c:
                if cm["tahun"]:
                    tren = count_by(df, cm["tahun"]).sort_values(cm["tahun"])
                    fig = px.line(tren, x=cm["tahun"], y="Unit",
                                  title="📈 Tren Tahunan", markers=True,
                                  color_discrete_sequence=["#38bdf8"],
                                  labels={cm["tahun"]: "Tahun"})
                    fig.update_traces(line_width=3, marker_size=8)
                    fig.update_layout(**PLOT_LAYOUT)
                    st.plotly_chart(fig, use_container_width=True)

            with col_d:
                if cm["dev"]:
                    top_dev = count_by_nlargest(df, cm["dev"], 10)
                    fig = px.bar(top_dev, x=cm["dev"], y="Unit",
                                 title="🏗️ Top 10 Pengembang",
                                 color_discrete_sequence=["#818cf8"],
                                 labels={cm["dev"]: "Pengembang"})
                    fig.update_layout(**PLOT_LAYOUT)
                    fig.update_xaxes(tickangle=45)
                    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------
# TAB 2 — TANYA AI
# ---------------------------------------------------------------
with tab2:
    st.markdown('<div class="section-header">🤖 Tanya AI tentang Data Tapera</div>', unsafe_allow_html=True)

    if not ANTHROPIC_KEY and not DEEPSEEK_KEY:
        st.error("⚠️ Tambahkan **ANTHROPIC_KEY** (Claude) atau **DEEPSEEK_KEY** di Streamlit Secrets → Settings → Secrets.")
        st.code("""ANTHROPIC_KEY = "sk-ant-..."
SUPABASE_URL = "https://..."
SUPABASE_KEY = "..."
""")
    else:
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(f'<div class="chat-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-ai">🤖 {msg["content"]}</div>', unsafe_allow_html=True)

        pertanyaan = st.text_area(
            "Ajukan pertanyaan tentang data FLPP:",
            placeholder="Contoh: Provinsi mana top 5 unit FLPP? / Berapa total realisasi 2024? / Bank mana yang dominan di Jawa Barat?",
            height=100, key="input_chat"
        )

        col_btn1, col_btn2 = st.columns([1, 5])
        with col_btn1:
            kirim = st.button("✉️ Kirim", use_container_width=True)
        with col_btn2:
            if st.button("🗑️ Hapus Riwayat"):
                st.session_state.chat_history = []
                st.rerun()

        if kirim and pertanyaan.strip():
            st.session_state.chat_history.append({"role": "user", "content": pertanyaan})

            with st.spinner("🔍 Mengambil data & menganalisis..."):
                # Ambil sampel data + kolom
                df_s = query_supabase(select="*", limit=5000)
                sample_cols = df_s.columns.tolist() if not df_s.empty else []

                if df_s.empty:
                    jawaban = "Tidak dapat mengambil data dari Supabase saat ini."
                else:
                    # Buat ringkasan statistik untuk AI
                    cm2 = detect_cols(sample_cols)
                    stats_lines = [f"Total baris dalam sampel: {len(df_s)}"]

                    if cm2["prov"]:
                        top5_prov = count_by_nlargest(df_s, cm2["prov"], 5)
                        stats_lines.append(f"Top 5 Provinsi: {top5_prov.to_string(index=False)}")
                    if cm2["bank"]:
                        top_bank = count_by_nlargest(df_s, cm2["bank"], 5)
                        stats_lines.append(f"Top Bank: {top_bank.to_string(index=False)}")
                    if cm2["tahun"]:
                        tren2 = count_by(df_s, cm2["tahun"]).sort_values(cm2["tahun"])
                        stats_lines.append(f"Tren per tahun: {tren2.to_string(index=False)}")
                    if cm2["nilai"] and cm2["nilai"] in df_s.columns:
                        df_s[cm2["nilai"]] = pd.to_numeric(df_s[cm2["nilai"]], errors="coerce")
                        stats_lines.append(f"Total nilai_flpp: Rp {df_s[cm2['nilai']].sum()/1e12:.2f} Triliun")
                    if cm2["dev"]:
                        top5_dev = count_by_nlargest(df_s, cm2["dev"], 5)
                        stats_lines.append(f"Top 5 Pengembang: {top5_dev.to_string(index=False)}")

                    # Juga kasih preview raw data (50 baris)
                    data_preview = df_s.head(50).to_csv(index=False)
                    stats_summary = "\n".join(stats_lines)

                    system_ai = """Kamu adalah analis data FLPP (Fasilitas Likuiditas Pembiayaan Perumahan) Tapera yang ahli.
Jawab pertanyaan berdasarkan data yang diberikan dalam bahasa Indonesia yang jelas dan informatif.
Sertakan insight penting, angka-angka kunci, dan kesimpulan yang actionable.
Gunakan emoji untuk memperjelas. Jangan sebut 'CSV' atau detail teknis."""

                    prompt_ai = f"""Pertanyaan user: {pertanyaan}

Ringkasan statistik dari data (sampel {len(df_s):,} baris):
{stats_summary}

Preview data mentah (50 baris pertama):
{data_preview}

Jawab pertanyaan user berdasarkan data di atas."""

                    jawaban = tanya_ai(prompt_ai, system_ai)

                    # Tampilkan tabel relevan jika pertanyaan tentang provinsi/bank/pengembang
                    keywords_tabel = ["provinsi", "bank", "pengembang", "pekerjaan", "kelamin", "tahun", "realisasi", "top", "terbanyak", "terbesar"]
                    if any(k in pertanyaan.lower() for k in keywords_tabel):
                        st.dataframe(df_s.head(100), use_container_width=True, height=250)

            st.session_state.chat_history.append({"role": "assistant", "content": jawaban})
            st.rerun()

# ---------------------------------------------------------------
# TAB 3 — ANALISIS DAERAH
# ---------------------------------------------------------------
with tab3:
    st.markdown('<div class="section-header">🗺️ Analisis Per Daerah</div>', unsafe_allow_html=True)

    df_prov_list = query_supabase(select="provinsi", limit=100000)
    if df_prov_list.empty or "provinsi" not in df_prov_list.columns:
        st.info("⏳ Data belum tersedia.")
    else:
        prov_list = sorted(df_prov_list["provinsi"].dropna().unique().tolist())
        selected_prov = st.selectbox("Pilih Provinsi:", prov_list)

        if selected_prov:
            f3 = {"provinsi": f"eq.{selected_prov}"}
            if tahun_filter != "Semua":
                f3["tahun_akad"] = f"eq.{tahun_filter}"

            df_prov = query_supabase(select="*", filters=f3, limit=10000)

            if not df_prov.empty:
                cols3 = df_prov.columns.tolist()
                cm3 = detect_cols(cols3)

                if cm3["nilai"] and cm3["nilai"] in df_prov.columns:
                    df_prov[cm3["nilai"]] = pd.to_numeric(df_prov[cm3["nilai"]], errors="coerce").fillna(0)

                m1, m2, m3 = st.columns(3)
                with m1:
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Total Unit</div><div class="metric-value">{len(df_prov):,}</div></div>', unsafe_allow_html=True)
                with m2:
                    val = df_prov[cm3["nilai"]].sum() / 1e9 if cm3["nilai"] else 0
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Nilai FLPP</div><div class="metric-value">Rp {val:.1f}M</div><div class="metric-sub">Miliar</div></div>', unsafe_allow_html=True)
                with m3:
                    v_kab = df_prov[cm3["kab"]].nunique() if cm3["kab"] else 0
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Kab/Kota</div><div class="metric-value">{v_kab}</div></div>', unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                col_x, col_y = st.columns(2)

                with col_x:
                    if cm3["kab"]:
                        top_kab = count_by_nlargest(df_prov, cm3["kab"], 10)
                        fig = px.bar(top_kab, x="Unit", y=cm3["kab"], orientation="h",
                                     title=f"Top 10 Kab/Kota — {selected_prov}",
                                     color_discrete_sequence=["#34d399"],
                                     labels={cm3["kab"]: "Kab/Kota"})
                        fig.update_layout(**PLOT_LAYOUT)
                        st.plotly_chart(fig, use_container_width=True)

                with col_y:
                    if cm3["dev"]:
                        top_dev_prov = count_by_nlargest(df_prov, cm3["dev"], 10)
                        fig = px.bar(top_dev_prov, x=cm3["dev"], y="Unit",
                                     title=f"Top 10 Pengembang — {selected_prov}",
                                     color_discrete_sequence=["#fb923c"],
                                     labels={cm3["dev"]: "Pengembang"})
                        fig.update_layout(**PLOT_LAYOUT)
                        fig.update_xaxes(tickangle=45)
                        st.plotly_chart(fig, use_container_width=True)

                # Tren tahunan per provinsi
                if cm3["tahun"]:
                    tren_prov = count_by(df_prov, cm3["tahun"]).sort_values(cm3["tahun"])
                    fig = px.line(tren_prov, x=cm3["tahun"], y="Unit",
                                  title=f"📈 Tren Tahunan — {selected_prov}",
                                  markers=True, color_discrete_sequence=["#38bdf8"],
                                  labels={cm3["tahun"]: "Tahun"})
                    fig.update_traces(line_width=3, marker_size=8)
                    fig.update_layout(**PLOT_LAYOUT)
                    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------
# TAB 4 — PENGEMBANG
# ---------------------------------------------------------------
with tab4:
    st.markdown('<div class="section-header">🏗️ Analisis Pengembang</div>', unsafe_allow_html=True)

    f4 = {}
    if tahun_filter != "Semua":
        f4["tahun_akad"] = f"eq.{tahun_filter}"

    df_dev_raw = query_supabase(select="*", filters=f4, limit=10000)
    if df_dev_raw.empty:
        st.info("⏳ Menunggu data...")
    else:
        cols4 = df_dev_raw.columns.tolist()
        cm4 = detect_cols(cols4)

        if cm4["dev"]:
            keyword = st.text_input("🔍 Cari nama pengembang:", placeholder="Contoh: GRAHA, CIPUTRA, PERUMNAS...")

            top_dev = count_by_nlargest(df_dev_raw, cm4["dev"], 20)
            if keyword:
                top_dev = top_dev[top_dev[cm4["dev"]].str.contains(keyword, case=False, na=False)]

            fig = px.bar(top_dev, x=cm4["dev"], y="Unit",
                         title="Top 20 Pengembang Nasional",
                         color="Unit", color_continuous_scale="Viridis",
                         labels={cm4["dev"]: "Pengembang"})
            fig.update_layout(**PLOT_LAYOUT)
            fig.update_xaxes(tickangle=45)
            fig.update_coloraxes(showscale=False)
            st.plotly_chart(fig, use_container_width=True)

            # White spot analysis
            if cm4["prov"]:
                st.markdown('<div class="section-header">⬜ White Spot Analysis</div>', unsafe_allow_html=True)
                st.caption("Provinsi dengan sedikit pengembang aktif — peluang pasar!")
                dev_per_prov = df_dev_raw.groupby(cm4["prov"])[cm4["dev"]].nunique().reset_index()
                dev_per_prov.columns = ["Provinsi", "Jumlah Pengembang"]
                dev_per_prov = dev_per_prov.sort_values("Jumlah Pengembang")
                fig2 = px.bar(dev_per_prov, x="Jumlah Pengembang", y="Provinsi",
                              orientation="h", title="Jumlah Pengembang per Provinsi",
                              color="Jumlah Pengembang", color_continuous_scale="RdYlGn")
                fig2.update_layout(**PLOT_LAYOUT)
                fig2.update_coloraxes(showscale=False)
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.warning("Kolom nama_pengembang tidak ditemukan di data.")

# ---------------------------------------------------------------
# TAB 5 — BANK & PEMBIAYAAN
# ---------------------------------------------------------------
with tab5:
    st.markdown('<div class="section-header">🏦 Analisis Bank & Pembiayaan</div>', unsafe_allow_html=True)

    f5 = {}
    if tahun_filter != "Semua":
        f5["tahun_akad"] = f"eq.{tahun_filter}"

    df_bank_raw = query_supabase(select="*", filters=f5, limit=10000)
    if df_bank_raw.empty:
        st.info("⏳ Menunggu data...")
    else:
        cols5 = df_bank_raw.columns.tolist()
        cm5 = detect_cols(cols5)

        if cm5["bank"]:
            if cm5["nilai"] and cm5["nilai"] in df_bank_raw.columns:
                df_bank_raw[cm5["nilai"]] = pd.to_numeric(df_bank_raw[cm5["nilai"]], errors="coerce").fillna(0)

            col_a, col_b = st.columns(2)

            with col_a:
                share = count_by_nlargest(df_bank_raw, cm5["bank"], 8)
                fig = px.pie(share, values="Unit", names=cm5["bank"],
                             title="Market Share Unit FLPP per Bank",
                             color_discrete_sequence=COLORS, hole=0.35)
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)

            with col_b:
                if cm5["nilai"]:
                    nilai_bank = df_bank_raw.groupby(cm5["bank"])[cm5["nilai"]].sum().nlargest(8).reset_index()
                    nilai_bank.columns = ["Bank", "Nilai"]
                    nilai_bank["Nilai_T"] = nilai_bank["Nilai"] / 1e12
                    fig = px.bar(nilai_bank, x="Bank", y="Nilai_T",
                                 title="Nilai FLPP per Bank (Triliun Rp)",
                                 color_discrete_sequence=["#38bdf8"])
                    fig.update_layout(**PLOT_LAYOUT)
                    fig.update_xaxes(tickangle=30)
                    st.plotly_chart(fig, use_container_width=True)

            # Bank dominan per provinsi
            if cm5["prov"]:
                st.markdown('<div class="section-header">🗺️ Bank Dominan per Provinsi</div>', unsafe_allow_html=True)
                dom = count_by(df_bank_raw, [cm5["prov"], cm5["bank"]])
                dom_idx = dom.groupby(cm5["prov"])["Unit"].idxmax()
                dom_bank = dom.loc[dom_idx, [cm5["prov"], cm5["bank"], "Unit"]]
                dom_bank.columns = ["Provinsi", "Bank Dominan", "Unit"]
                dom_bank = dom_bank.sort_values("Unit", ascending=False)
                st.dataframe(dom_bank, use_container_width=True, hide_index=True)
        else:
            st.warning("Kolom bank tidak ditemukan di data.")

# ---------------------------------------------------------------
# TAB 6 — PROFIL PEMBELI
# ---------------------------------------------------------------
with tab6:
    st.markdown('<div class="section-header">👥 Profil Pembeli FLPP</div>', unsafe_allow_html=True)

    f6 = {}
    if tahun_filter != "Semua":
        f6["tahun_akad"] = f"eq.{tahun_filter}"

    df_profil = query_supabase(select="*", filters=f6, limit=10000)
    if df_profil.empty:
        st.info("⏳ Menunggu data...")
    else:
        cols6 = df_profil.columns.tolist()
        cm6 = detect_cols(cols6)

        for key in ["harga", "peng", "tenor"]:
            if cm6[key] and cm6[key] in df_profil.columns:
                df_profil[cm6[key]] = pd.to_numeric(df_profil[cm6[key]], errors="coerce").fillna(0)

        row1_a, row1_b = st.columns(2)

        with row1_a:
            if cm6["gender"]:
                gender_data = count_by(df_profil, cm6["gender"])
                fig = px.pie(gender_data, values="Unit", names=cm6["gender"],
                             title="Distribusi Jenis Kelamin",
                             color_discrete_sequence=["#38bdf8", "#f472b6"], hole=0.4)
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom kelamin/jenis_kelamin tidak ditemukan")

        with row1_b:
            if cm6["profesi"]:
                profesi_data = count_by_nlargest(df_profil, cm6["profesi"], 8)
                fig = px.bar(profesi_data, x="Unit", y=cm6["profesi"], orientation="h",
                             title="Top Pekerjaan Pembeli",
                             color_discrete_sequence=["#34d399"],
                             labels={cm6["profesi"]: "Pekerjaan"})
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom pekerjaan/profesi tidak ditemukan")

        row2_a, row2_b = st.columns(2)

        with row2_a:
            if cm6["tenor"]:
                tenor_data = count_by(df_profil, cm6["tenor"]).sort_values(cm6["tenor"])
                fig = px.bar(tenor_data, x=cm6["tenor"], y="Unit",
                             title="Distribusi Tenor KPR",
                             color_discrete_sequence=["#818cf8"],
                             labels={cm6["tenor"]: "Tenor (Tahun)"})
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom tenor tidak ditemukan")

        with row2_b:
            if cm6["harga"] and df_profil[cm6["harga"]].sum() > 0:
                fig = px.histogram(df_profil[df_profil[cm6["harga"]] > 0],
                                   x=cm6["harga"], title="Distribusi Harga Rumah",
                                   color_discrete_sequence=["#fb923c"], nbins=30,
                                   labels={cm6["harga"]: "Harga Rumah (Rp)"})
                fig.update_layout(**PLOT_LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kolom harga_rumah tidak ditemukan")

        # Distribusi penghasilan
        if cm6["peng"] and df_profil[cm6["peng"]].sum() > 0:
            st.markdown('<div class="section-header">💰 Distribusi Penghasilan Pembeli</div>', unsafe_allow_html=True)
            fig = px.histogram(df_profil[df_profil[cm6["peng"]] > 0],
                               x=cm6["peng"], title="Distribusi Penghasilan Pembeli",
                               color_discrete_sequence=["#facc15"], nbins=30,
                               labels={cm6["peng"]: "Penghasilan (Rp)"})
            fig.update_layout(**PLOT_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
