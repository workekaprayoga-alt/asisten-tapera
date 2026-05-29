import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import json
import re

# ============================================================
# KONFIGURASI
# ============================================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
GROQ_KEY     = st.secrets.get("GROQ_KEY", "")
TABLE_NAME   = "realisasi"

# Skema kolom yang diketahui dari data nyata
SCHEMA = {
    "id": "integer, primary key",
    "tahun_akad": "integer, tahun akad kredit (contoh: 2023)",
    "tahun_realisasi": "integer, tahun realisasi (contoh: 2023)",
    "bank": "text, nama bank pelaksana (contoh: BTN, BNI, BRI, Mandiri)",
    "asosiasi": "text, nama asosiasi pengembang",
    "jenis_rumah": "text, jenis rumah",
    "provinsi": "text, nama provinsi (huruf kapital, contoh: JAWA BARAT)",
    "kabupaten": "text, nama kabupaten/kota",
    "kecamatan": "text, nama kecamatan",
    "kelurahan": "text, nama kelurahan",
    "kelamin": "text, jenis kelamin pembeli (L/P atau LAKI-LAKI/PEREMPUAN)",
    "pekerjaan": "text, pekerjaan/profesi pembeli",
    "penghasilan": "numeric, penghasilan bulanan pembeli (rupiah)",
    "nama_pengembang": "text, nama perusahaan pengembang",
    "nama_perumahan": "text, nama perumahan/cluster",
    "luas_bangunan": "numeric, luas bangunan (m2)",
    "luas_tanah": "numeric, luas tanah (m2)",
    "harga_rumah": "numeric, harga rumah (rupiah)",
    "tenor": "integer, tenor KPR (tahun)",
    "suku_bunga_kpr": "numeric, suku bunga KPR (%)",
    "nilai_flpp": "numeric, nilai kredit FLPP (rupiah)",
    "tgl_akad": "date, tanggal akad",
    "tanggal_pencairan": "date, tanggal pencairan dana",
}

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Asisten AI Tapera FLPP",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# CSS — tampilan chat bersih
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
.stApp {
    background: #0f1117;
    color: #ececec;
}

/* Header */
.app-header {
    text-align: center;
    padding: 32px 0 16px 0;
    border-bottom: 1px solid #2a2a2a;
    margin-bottom: 24px;
}
.app-title {
    font-size: 24px;
    font-weight: 700;
    color: #ffffff;
    margin: 0;
}
.app-sub {
    font-size: 13px;
    color: #666;
    margin-top: 4px;
}

/* Chat bubbles */
.bubble-wrap {
    display: flex;
    gap: 12px;
    margin: 16px 0;
    align-items: flex-start;
}
.bubble-wrap.user {
    flex-direction: row-reverse;
}
.avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    flex-shrink: 0;
    margin-top: 2px;
}
.avatar.ai   { background: #1a3a5c; }
.avatar.user { background: #2d2d2d; }
.bubble {
    padding: 12px 16px;
    border-radius: 16px;
    max-width: 85%;
    font-size: 14px;
    line-height: 1.6;
}
.bubble.ai {
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    color: #e0e0e0;
    border-radius: 4px 16px 16px 16px;
}
.bubble.user {
    background: #1d4ed8;
    color: white;
    border-radius: 16px 4px 16px 16px;
}

/* Status pills */
.status-ok  { color: #34d399; font-size: 12px; }
.status-err { color: #f87171; font-size: 12px; }

/* Quick questions */
.qq-label {
    color: #555;
    font-size: 12px;
    text-align: center;
    margin-bottom: 10px;
}

/* Typing indicator */
.typing {
    display: flex;
    gap: 4px;
    padding: 12px 16px;
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 4px 16px 16px 16px;
    width: fit-content;
}
.dot {
    width: 8px; height: 8px;
    background: #4a7fc1;
    border-radius: 50%;
    animation: bounce 1.2s infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
    40% { transform: translateY(-6px); opacity: 1; }
}

input, textarea {
    background: #1a1a1a !important;
    color: #fff !important;
    border: 1px solid #333 !important;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# SUPABASE HELPERS
# ============================================================
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

@st.cache_data(ttl=600)
def count_total() -> int:
    h = sb_headers()
    h["Prefer"] = "count=exact"
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h, params={"select": "id", "limit": "1"}, timeout=15
        )
        ct = r.headers.get("content-range", "0/0")
        return int(ct.split("/")[-1]) if "/" in ct else 0
    except:
        return 0

@st.cache_data(ttl=600)
def get_stats() -> dict:
    """Ambil statistik ringkas untuk konteks AI."""
    try:
        # Sample kecil untuk stats
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=sb_headers(),
            params={"select": "bank,provinsi,tahun_akad,nilai_flpp", "limit": "5000"},
            timeout=30
        )
        df = pd.DataFrame(r.json()) if r.ok else pd.DataFrame()
        if df.empty:
            return {}
        stats = {
            "banks": sorted(df["bank"].dropna().unique().tolist()) if "bank" in df else [],
            "provinces": sorted(df["provinsi"].dropna().unique().tolist()) if "provinsi" in df else [],
            "years": sorted(df["tahun_akad"].dropna().unique().tolist()) if "tahun_akad" in df else [],
        }
        if "nilai_flpp" in df:
            df["nilai_flpp"] = pd.to_numeric(df["nilai_flpp"], errors="coerce")
            stats["avg_nilai"] = df["nilai_flpp"].mean()
        return stats
    except:
        return {}

def query_data(select="*", filters=None, limit=2000, order=None) -> pd.DataFrame:
    params = {"select": select, "limit": str(limit)}
    if filters:
        params.update(filters)
    if order:
        params["order"] = order
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=sb_headers(), params=params, timeout=30
        )
        data = r.json()
        return pd.DataFrame(data) if isinstance(data, list) and data else pd.DataFrame()
    except:
        return pd.DataFrame()

# ============================================================
# GROQ AI
# ============================================================
def call_groq(messages: list, temperature=0.3, max_tokens=2000) -> str:
    if not GROQ_KEY:
        return "⚠️ GROQ_KEY belum diisi di Streamlit Secrets."
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Error Groq: {e}"

def ai_plan_query(pertanyaan: str, stats: dict) -> dict:
    """Minta AI buat rencana query ke Supabase."""
    schema_str = "\n".join([f"- {k}: {v}" for k, v in SCHEMA.items()])
    banks_str  = ", ".join(stats.get("banks", [])[:20])
    provs_str  = ", ".join(stats.get("provinces", [])[:15])
    years_str  = ", ".join([str(y) for y in stats.get("years", [])])

    system = f"""Kamu adalah query planner untuk database Supabase PostgreSQL.
Tugasmu: ubah pertanyaan user menjadi parameter query REST API Supabase.

SKEMA TABEL "realisasi":
{schema_str}

NILAI YANG ADA DI DATA:
- Bank: {banks_str}
- Provinsi (sebagian): {provs_str}
- Tahun akad: {years_str}
- Catatan: setiap baris = 1 unit rumah (tidak ada kolom jumlah_unit)

OUTPUT: JSON saja, tanpa penjelasan, tanpa markdown. Format:
{{
  "select": "kolom1,kolom2,...",
  "filters": {{"kolom": "eq.nilai", "kolom2": "gte.angka"}},
  "order": "kolom.desc",
  "limit": 3000,
  "needs_chart": true/false,
  "chart_type": "bar/pie/line/histogram/none",
  "chart_x": "nama_kolom_x",
  "chart_y": "Unit",
  "chart_title": "judul grafik"
}}

Filter Supabase: eq.VALUE, neq.VALUE, gt.VALUE, gte.VALUE, lt.VALUE, lte.VALUE, ilike.*VALUE*, in.(A,B,C)
Untuk agregasi (GROUP BY), pilih kolom yang mau digroup saja di select dan limit 5000+.
Kalau pertanyaan umum yang tidak butuh data spesifik: kembalikan {{"skip_query": true}}"""

    raw = call_groq([
        {"role": "system", "content": system},
        {"role": "user", "content": pertanyaan}
    ], temperature=0.1, max_tokens=500)

    raw = raw.strip().strip("```json").strip("```").strip()
    # Cari JSON di output
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass
    return {"select": "*", "limit": 1000}

def ai_analyze(pertanyaan: str, df: pd.DataFrame, total_rows: int, stats: dict) -> str:
    """Minta AI analisa data hasil query."""
    schema_str = "\n".join([f"- {k}: {v}" for k, v in SCHEMA.items()])

    if df.empty:
        data_info = "Tidak ada data ditemukan untuk query ini."
    else:
        # Ringkas data sebelum kirim ke AI
        if len(df) > 100:
            # Buat summary per group jika memungkinkan
            summary_parts = []
            for col in df.columns:
                if df[col].dtype == object and df[col].nunique() < 50:
                    vc = df[col].value_counts().head(15)
                    summary_parts.append(f"\n{col} (top values):\n{vc.to_string()}")
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    summary_parts.append(f"\n{col}: min={df[col].min():,.0f}, max={df[col].max():,.0f}, mean={df[col].mean():,.0f}, sum={df[col].sum():,.0f}")
            data_info = f"Total baris hasil query: {len(df):,} (dari total {total_rows:,} baris di database)\n"
            data_info += "\n".join(summary_parts)
            data_info += f"\n\nSample 10 baris pertama:\n{df.head(10).to_string(index=False)}"
        else:
            data_info = f"Total baris hasil query: {len(df):,} (dari total {total_rows:,} baris di database)\n"
            data_info += df.to_string(index=False)

    banks  = ", ".join(stats.get("banks", [])[:10])
    years  = ", ".join([str(y) for y in stats.get("years", [])])

    system = f"""Kamu adalah asisten AI ahli analisis data perumahan FLPP (Fasilitas Likuiditas Pembiayaan Perumahan) Indonesia yang dikembangkan oleh Tapera.

Kamu punya akses ke database realisasi KPR FLPP dengan {total_rows:,} baris data.
Bank yang ada: {banks}
Tahun data: {years}

SKEMA:
{schema_str}

Panduan menjawab:
- Jawab dalam bahasa Indonesia yang natural dan jelas
- Kalau ada data, analisa dengan spesifik — sebutkan angka, persentase, perbandingan
- Kasih insight yang actionable, bukan hanya deskripsi
- Kalau pertanyaan umum tentang FLPP/perumahan, jawab dari pengetahuanmu
- Gunakan format yang enak dibaca (bullet point, angka tebal dengan **angka**)
- Jangan sebut "CSV", "query", "database" — bicara natural
- Kalau data kurang untuk menjawab secara pasti, bilang dengan jujur"""

    prompt = f"""Pertanyaan: {pertanyaan}

Data yang saya temukan:
{data_info}

Analisa dan jawab pertanyaan di atas."""

    return call_groq([
        {"role": "system", "content": system},
        {"role": "user", "content": prompt}
    ], temperature=0.4, max_tokens=1500)

def make_chart(df: pd.DataFrame, plan: dict) -> go.Figure | None:
    """Buat grafik dari data sesuai plan AI."""
    chart_type = plan.get("chart_type", "none")
    if chart_type == "none" or df.empty:
        return None

    chart_x     = plan.get("chart_x", "")
    chart_title = plan.get("chart_title", "")

    LAYOUT = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.8)",
        font=dict(family="Inter", color="#94a3b8", size=12),
        title_font=dict(color="#e2e8f0", size=14),
        xaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
        yaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
        margin=dict(t=50, b=40, l=10, r=10),
    )
    COLORS = ["#38bdf8","#818cf8","#34d399","#fb923c","#f472b6","#a3e635","#facc15","#60a5fa"]

    try:
        # Buat summary data untuk chart
        if chart_x and chart_x in df.columns:
            # Group by chart_x, count rows
            summary = df.groupby(chart_x).size().reset_index(name="Unit")
            # Tambah kolom numerik jika ada
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]) and col != chart_x:
                    agg = df.groupby(chart_x)[col].sum().reset_index()
                    summary = summary.merge(agg, on=chart_x, how="left")

            summary = summary.nlargest(20, "Unit") if len(summary) > 20 else summary
            summary[chart_x] = summary[chart_x].astype(str)

            if chart_type == "bar":
                fig = px.bar(summary, x="Unit", y=chart_x, orientation="h",
                             title=chart_title, color_discrete_sequence=["#38bdf8"])
                fig.update_layout(**LAYOUT)
                return fig

            elif chart_type == "pie":
                summary = summary.nlargest(10, "Unit")
                fig = px.pie(summary, values="Unit", names=chart_x,
                             title=chart_title, hole=0.4,
                             color_discrete_sequence=COLORS)
                fig.update_layout(**LAYOUT)
                return fig

            elif chart_type == "line":
                summary = summary.sort_values(chart_x)
                fig = px.line(summary, x=chart_x, y="Unit",
                              title=chart_title, markers=True,
                              color_discrete_sequence=["#38bdf8"])
                fig.update_traces(line_width=2.5, marker_size=7)
                fig.update_layout(**LAYOUT)
                return fig

        # Histogram untuk kolom numerik
        if chart_type == "histogram":
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            if num_cols:
                col = chart_x if chart_x in num_cols else num_cols[0]
                df[col] = pd.to_numeric(df[col], errors="coerce")
                fig = px.histogram(df.dropna(subset=[col]), x=col,
                                   title=chart_title, nbins=30,
                                   color_discrete_sequence=["#818cf8"])
                fig.update_layout(**LAYOUT)
                return fig
    except:
        pass
    return None

# ============================================================
# SESSION STATE
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "stats" not in st.session_state:
    st.session_state.stats = None
if "total" not in st.session_state:
    st.session_state.total = 0

# ============================================================
# LOAD DATA STATS (sekali saja)
# ============================================================
if SUPABASE_KEY and st.session_state.total == 0:
    st.session_state.total = count_total()
    st.session_state.stats = get_stats()

# ============================================================
# HEADER
# ============================================================
st.markdown("""
<div class="app-header">
    <p class="app-title">🏠 Asisten AI Tapera FLPP</p>
    <p class="app-sub">Tanya apa saja tentang data realisasi KPR FLPP Indonesia</p>
</div>
""", unsafe_allow_html=True)

# Status bar kecil
total = st.session_state.total
stats = st.session_state.stats or {}

col_s1, col_s2, col_s3, col_s4 = st.columns(4)
with col_s1:
    if total > 0:
        st.markdown(f'<p class="status-ok">✓ Supabase ({total:,} baris)</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-err">✗ Supabase tidak terhubung</p>', unsafe_allow_html=True)
with col_s2:
    if GROQ_KEY:
        st.markdown('<p class="status-ok">✓ Groq AI (Llama 3.3)</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-err">✗ GROQ_KEY belum diisi</p>', unsafe_allow_html=True)
with col_s3:
    banks = stats.get("banks", [])
    st.markdown(f'<p class="status-ok">✓ {len(banks)} bank terdeteksi</p>' if banks else '<p class="status-err">– Bank belum terbaca</p>', unsafe_allow_html=True)
with col_s4:
    years = stats.get("years", [])
    st.markdown(f'<p class="status-ok">✓ Tahun {min(years)}–{max(years)}</p>' if years else '<p class="status-err">– Tahun belum terbaca</p>', unsafe_allow_html=True)

st.markdown("---")

# ============================================================
# AREA CHAT
# ============================================================
chat_area = st.container()

with chat_area:
    if not st.session_state.messages:
        # Pesan selamat datang
        st.markdown("""
        <div class="bubble-wrap">
            <div class="avatar ai">🏠</div>
            <div class="bubble ai">
                Halo! Saya asisten AI untuk data FLPP Tapera. Saya punya akses ke database realisasi KPR FLPP Indonesia dan bisa membantu Anda menganalisis data tersebut.<br><br>
                Tanyakan apa saja — mulai dari statistik nasional, analisis per provinsi, performa bank, profil pembeli, tren tahunan, atau apa pun yang ingin Anda ketahui tentang program FLPP.
            </div>
        </div>
        """, unsafe_allow_html=True)

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f"""
            <div class="bubble-wrap user">
                <div class="avatar user">👤</div>
                <div class="bubble user">{msg["content"]}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="bubble-wrap">
                <div class="avatar ai">🏠</div>
                <div class="bubble ai">{msg["content"].replace(chr(10), "<br>")}</div>
            </div>
            """, unsafe_allow_html=True)
            # Tampilkan grafik jika ada
            if msg.get("chart") is not None:
                st.plotly_chart(msg["chart"], use_container_width=True)
            # Tampilkan tabel jika ada
            if msg.get("table") is not None and not msg["table"].empty:
                with st.expander("📋 Lihat data mentah"):
                    st.dataframe(msg["table"].head(200), use_container_width=True, hide_index=True)

# ============================================================
# QUICK QUESTIONS
# ============================================================
if len(st.session_state.messages) == 0:
    st.markdown('<p class="qq-label">💡 Pertanyaan cepat:</p>', unsafe_allow_html=True)
    qq_cols = st.columns(3)
    quick_questions = [
        "Berapa total unit FLPP yang sudah terealisasi?",
        "Provinsi mana yang paling banyak unit FLPP?",
        "Bank mana yang paling aktif dalam pembiayaan FLPP?",
        "Bagaimana tren realisasi FLPP per tahun?",
        "Apa profil rata-rata pembeli rumah FLPP?",
        "Pengembang mana yang paling banyak unit FLPP?",
    ]
    for i, qq in enumerate(quick_questions):
        with qq_cols[i % 3]:
            if st.button(qq, key=f"qq_{i}", use_container_width=True):
                st.session_state.pending_question = qq
                st.rerun()

# ============================================================
# INPUT CHAT
# ============================================================
st.markdown("<br>", unsafe_allow_html=True)
input_col, btn_col = st.columns([6, 1])

with input_col:
    user_input = st.text_input(
        "Ketik pertanyaan...",
        placeholder="Tanya apa saja tentang data FLPP...",
        label_visibility="collapsed",
        key="chat_input"
    )

with btn_col:
    kirim = st.button("Kirim ➤", use_container_width=True)

col_clear, _ = st.columns([1, 5])
with col_clear:
    if st.button("🗑️ Reset chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ============================================================
# PROSES PERTANYAAN
# ============================================================
question = None
if kirim and user_input.strip():
    question = user_input.strip()
elif hasattr(st.session_state, "pending_question"):
    question = st.session_state.pending_question
    del st.session_state.pending_question

if question:
    st.session_state.messages.append({"role": "user", "content": question})

    with st.spinner("🔍 Menganalisis..."):
        stats  = st.session_state.stats or {}
        total  = st.session_state.total

        # Step 1: AI buat rencana query
        plan = ai_plan_query(question, stats)

        df_result = pd.DataFrame()
        fig = None

        # Step 2: Jalankan query kalau perlu
        if not plan.get("skip_query"):
            filters = plan.get("filters", {})
            select  = plan.get("select", "*")
            limit   = plan.get("limit", 2000)
            order   = plan.get("order", None)

            df_result = query_data(
                select=select,
                filters=filters if filters else None,
                limit=limit,
                order=order
            )

            # Step 3: Buat grafik jika diminta
            if plan.get("needs_chart") and not df_result.empty:
                fig = make_chart(df_result, plan)

        # Step 4: AI analisa dan jawab
        jawaban = ai_analyze(question, df_result, total, stats)

    # Simpan ke history
    st.session_state.messages.append({
        "role": "assistant",
        "content": jawaban,
        "chart": fig,
        "table": df_result if not df_result.empty and len(df_result) <= 500 else None,
    })
    st.rerun()
