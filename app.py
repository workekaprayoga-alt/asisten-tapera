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

# Skema kolom — nama PERSIS seperti di Supabase
SCHEMA = {
    "id":                "integer, primary key, JANGAN dipakai untuk analisis",
    "tahun_akad":        "integer, tahun akad kredit (2022-2024)",
    "tahun_realisasi":   "integer, tahun realisasi pencairan",
    "bank":              "text, nama bank pelaksana FLPP",
    "asosiasi":          "text, nama asosiasi pengembang",
    "jenis_rumah":       "text, jenis/tipe rumah",
    "provinsi":          "text, nama provinsi HURUF KAPITAL (contoh: JAWA BARAT, DKI JAKARTA)",
    "kabupaten":         "text, nama kabupaten atau kota",
    "kecamatan":         "text, nama kecamatan",
    "kelurahan":         "text, nama kelurahan/desa",
    "kelamin":           "text, jenis kelamin pembeli (nilai: L atau P, atau LAKI-LAKI/PEREMPUAN)",
    "pekerjaan":         "text, pekerjaan atau profesi pembeli",
    "penghasilan":       "numeric, penghasilan bulanan pembeli dalam rupiah",
    "nama_pengembang":   "text, nama perusahaan pengembang perumahan",
    "nama_perumahan":    "text, nama perumahan atau cluster",
    "luas_bangunan":     "numeric, luas bangunan dalam m2",
    "luas_tanah":        "numeric, luas tanah dalam m2",
    "harga_rumah":       "numeric, harga jual rumah dalam rupiah",
    "tenor":             "integer, jangka waktu KPR dalam tahun",
    "suku_bunga_kpr":    "numeric, suku bunga KPR dalam persen",
    "nilai_flpp":        "numeric, nilai kredit FLPP yang dicairkan dalam rupiah",
    "tgl_akad":          "date, tanggal penandatanganan akad kredit",
    "tanggal_pencairan": "date, tanggal pencairan dana FLPP",
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
# CSS
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #0f1117; color: #ececec; }
.app-header {
    text-align: center; padding: 28px 0 14px 0;
    border-bottom: 1px solid #2a2a2a; margin-bottom: 20px;
}
.app-title { font-size: 22px; font-weight: 700; color: #fff; margin: 0; }
.app-sub   { font-size: 13px; color: #555; margin-top: 4px; }
.bubble-wrap { display: flex; gap: 12px; margin: 14px 0; align-items: flex-start; }
.bubble-wrap.user { flex-direction: row-reverse; }
.avatar {
    width: 32px; height: 32px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; flex-shrink: 0; margin-top: 2px;
}
.avatar.ai   { background: #1a3a5c; }
.avatar.user { background: #2d2d2d; }
.bubble {
    padding: 12px 16px; border-radius: 16px;
    max-width: 85%; font-size: 14px; line-height: 1.65;
}
.bubble.ai {
    background: #1a1a2e; border: 1px solid #2a2a4a;
    color: #e0e0e0; border-radius: 4px 16px 16px 16px;
}
.bubble.user {
    background: #1d4ed8; color: white;
    border-radius: 16px 4px 16px 16px;
}
.status-ok  { color: #34d399; font-size: 12px; }
.status-err { color: #f87171; font-size: 12px; }
.qq-label   { color: #555; font-size: 12px; text-align: center; margin-bottom: 10px; }
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

@st.cache_data(ttl=3600)
def count_total() -> int:
    """Hitung total baris dengan count=exact — ini angka paling akurat."""
    h = sb_headers()
    h["Prefer"] = "count=exact"
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h,
            params={"select": "id", "limit": "1"},
            timeout=20
        )
        ct = r.headers.get("content-range", "")
        if "/" in ct:
            return int(ct.split("/")[-1])
    except:
        pass
    return 0

@st.cache_data(ttl=3600)
def get_stats() -> dict:
    """
    Ambil nilai-nilai unik per kolom kunci langsung dari Supabase.
    Menggunakan order asc+desc dan limit besar supaya dapat semua nilai
    meskipun data 1 juta+ baris.
    """
    base = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()

    def fetch_unique(col: str, limit: int = 5000) -> list:
        """Ambil nilai unik kolom dengan dua pass (asc + desc) untuk coverage penuh."""
        result = set()
        for direction in [f"{col}.asc", f"{col}.desc"]:
            try:
                r = requests.get(base, headers=h,
                    params={"select": col, "order": direction, "limit": str(limit)},
                    timeout=25)
                if r.ok and isinstance(r.json(), list):
                    vals = pd.DataFrame(r.json())[col].dropna().unique().tolist()
                    result.update(vals)
            except:
                pass
        return sorted(result)

    banks     = fetch_unique("bank", 1000)
    provinces = fetch_unique("provinsi", 1000)

    # Tahun dari dua kolom berbeda
    years_raw = fetch_unique("tahun_akad", 5000) + fetch_unique("tahun_realisasi", 5000)
    years = sorted({int(y) for y in years_raw if str(y).lstrip("-").isdigit() and 2000 < int(y) < 2100})

    return {
        "banks":     banks,
        "provinces": provinces,
        "years":     years,
    }

def query_supabase(select: str = "*", filters: dict = None,
                   order: str = None, limit: int = 10000) -> pd.DataFrame:
    """
    Query data dari Supabase.
    CATATAN: Supabase REST default limit = 1000. Kita selalu set limit eksplisit.
    """
    params = {"select": select, "limit": str(limit)}
    if filters:
        # Validasi filter — hanya masukkan yang nilainya tidak kosong
        for k, v in filters.items():
            if v and str(v).strip():
                params[k] = str(v)
    if order and str(order).strip() not in ["", "null", "None"]:
        params["order"] = order
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=sb_headers(),
            params=params,
            timeout=45
        )
        if not r.ok:
            return pd.DataFrame()
        data = r.json()
        if isinstance(data, list) and data:
            return pd.DataFrame(data)
    except:
        pass
    return pd.DataFrame()

def count_with_filter(filters: dict = None) -> int:
    """Hitung jumlah baris dengan filter tertentu (count=exact)."""
    h = sb_headers()
    h["Prefer"] = "count=exact"
    params = {"select": "id", "limit": "1"}
    if filters:
        for k, v in filters.items():
            if v and str(v).strip():
                params[k] = str(v)
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h, params=params, timeout=20
        )
        ct = r.headers.get("content-range", "")
        if "/" in ct:
            return int(ct.split("/")[-1])
    except:
        pass
    return 0

# ============================================================
# GROQ AI
# ============================================================
def call_groq(messages: list, temperature: float = 0.3, max_tokens: int = 1500) -> str:
    if not GROQ_KEY:
        return "⚠️ GROQ_KEY belum diisi di Streamlit Secrets."
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json"
            },
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

def parse_json_safe(text: str) -> dict:
    """Parse JSON dari output AI — tahan terhadap markdown fence dan teks tambahan."""
    text = text.strip()
    # Hapus markdown fence
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    # Cari objek JSON pertama
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}

# ============================================================
# AI: BUAT QUERY PLAN
# ============================================================
def ai_plan_query(pertanyaan: str, stats: dict, total: int) -> dict:
    """
    AI buat rencana query. Menghasilkan dict dengan:
    - select, filters, order, limit  → parameter query Supabase
    - skip_query                     → True jika tidak perlu query (misal pertanyaan total)
    - use_count_api                  → True jika pakai count=exact bukan ambil data
    - count_filters                  → filter untuk count API
    - needs_chart, chart_type, chart_x, chart_title
    - answer_hint                    → petunjuk untuk AI analis
    """
    schema_str = "\n".join([f"  {k}: {v}" for k, v in SCHEMA.items()])
    banks_str  = ", ".join([f'"{b}"' for b in stats.get("banks", [])[:30]])
    provs_str  = ", ".join([f'"{p}"' for p in stats.get("provinces", [])[:30]])
    years_str  = str(stats.get("years", []))

    system = f"""Kamu adalah sistem query planner untuk database FLPP Tapera.

=== FAKTA KRITIS YANG HARUS SELALU DIINGAT ===
- SETIAP BARIS = 1 unit rumah FLPP yang terealisasi (tidak ada kolom jumlah_unit)
- Total baris di database = {total:,} = {total:,} unit rumah
- Ini angka PASTI dari sistem, bukan estimasi

=== SKEMA TABEL "realisasi" ===
{schema_str}

=== NILAI YANG ADA DI DATA ===
Bank: {banks_str}
Provinsi: {provs_str}
Tahun: {years_str}

=== PANDUAN MEMBUAT QUERY ===

JENIS PERTANYAAN → STRATEGI:

1. "Berapa total unit?" / "Berapa jumlah keseluruhan?"
   → skip_query: true (total sudah diketahui = {total:,})

2. "Per provinsi / ranking provinsi / distribusi wilayah"
   → select: "provinsi", limit: 100000, needs_chart: true, chart_type: "bar", chart_x: "provinsi"

3. "Per bank / bank mana?"
   → select: "bank", limit: 100000, needs_chart: true, chart_type: "bar", chart_x: "bank"

4. "Per tahun / tren tahunan"
   → select: "tahun_akad", limit: 100000, needs_chart: true, chart_type: "line", chart_x: "tahun_akad"

5. "Per pengembang / developer"
   → select: "nama_pengembang", limit: 100000

6. "Profil pembeli / gender / pekerjaan"
   → select: "kelamin,pekerjaan,penghasilan,tenor,harga_rumah", limit: 20000

7. "Nilai FLPP / kredit / pembiayaan"
   → select: "nilai_flpp,bank,provinsi,tahun_akad", limit: 20000

8. "Harga rumah / distribusi harga"
   → select: "harga_rumah,provinsi,bank,jenis_rumah", limit: 20000, needs_chart: true, chart_type: "histogram", chart_x: "harga_rumah"

9. Filter spesifik (provinsi/bank/tahun tertentu):
   → tambahkan filters dengan nilai PERSIS seperti di data
   → provinsi: "eq.JAWA BARAT" (huruf kapital persis)
   → tahun_akad: "eq.2023"
   → bank: "eq.BTN" (sesuai nilai di data)

10. Pertanyaan umum tentang FLPP (bukan spesifik data):
    → skip_query: true

=== FORMAT OUTPUT ===
Kembalikan JSON murni saja. TIDAK BOLEH ada teks di luar JSON:
{{
  "select": "kolom1,kolom2",
  "filters": {{}},
  "order": null,
  "limit": 50000,
  "skip_query": false,
  "use_count_api": false,
  "count_filters": {{}},
  "needs_chart": false,
  "chart_type": "none",
  "chart_x": "",
  "chart_title": "",
  "answer_hint": "petunjuk singkat untuk AI analis"
}}"""

    raw = call_groq(
        [{"role": "system", "content": system},
         {"role": "user", "content": pertanyaan}],
        temperature=0.05,
        max_tokens=500
    )

    plan = parse_json_safe(raw)

    # ── Safety checks ──────────────────────────────────────────────────────────
    # Jika select hanya "id" → tidak berguna untuk analisis, skip saja
    sel = plan.get("select", "").strip()
    if sel in ("id", ""):
        plan["skip_query"] = True

    # Pastikan limit adalah integer
    try:
        plan["limit"] = int(plan.get("limit", 10000))
    except:
        plan["limit"] = 10000

    # Hapus filter kosong / null
    if isinstance(plan.get("filters"), dict):
        plan["filters"] = {k: v for k, v in plan["filters"].items()
                           if v and str(v).strip() not in ("", "null", "None")}

    # Fallback jika plan kosong
    if not plan:
        plan = {"select": "*", "limit": 5000, "skip_query": False}

    return plan

# ============================================================
# AI: ANALISIS & JAWAB
# ============================================================
def build_data_summary(df: pd.DataFrame, total_rows: int) -> str:
    """
    Bangun ringkasan data yang informatif untuk dikirim ke AI analis.
    Prioritas: COUNT per kategori > statistik numerik > sample baris.
    """
    if df.empty:
        return (
            f"Tidak ada data spesifik yang diambil untuk pertanyaan ini.\n"
            f"FAKTA PASTI: Total unit FLPP di database = {total_rows:,} unit.\n"
            f"(Setiap 1 baris data = 1 unit rumah yang dibiayai FLPP)"
        )

    parts = []
    parts.append(f"Data yang dianalisis: {len(df):,} baris (sampel dari {total_rows:,} total unit)")
    parts.append(f"ANGKA TOTAL PASTI: {total_rows:,} unit rumah FLPP terealisasi")
    parts.append("")

    # Kolom kategorik → COUNT + persentase (paling berguna)
    cat_cols = [c for c in df.columns
                if c not in ("id",) and (df[c].dtype == object or str(df[c].dtype) == "category")]

    for col in cat_cols:
        n_unique = df[col].nunique()
        if n_unique == 0:
            continue
        if n_unique == 1:
            parts.append(f"{col}: {df[col].iloc[0]}")
            continue
        if n_unique > 500:
            parts.append(f"{col}: {n_unique} nilai unik (terlalu banyak untuk ditampilkan)")
            continue

        vc  = df[col].value_counts()
        top = vc.head(25)
        pct = (top / len(df) * 100).round(1)
        rows = [f"  • {k}: {v:,} unit ({p}%)"
                for (k, v), p in zip(top.items(), pct)]
        cover = (top.sum() / len(df) * 100)
        parts.append(
            f"--- {col.upper()} ({n_unique} nilai unik) ---\n" +
            "\n".join(rows) +
            (f"\n  (menampilkan {len(top)} teratas, mencakup {cover:.0f}% data)" if len(vc) > 25 else "")
        )
        parts.append("")

    # Kolom numerik → statistik lengkap
    num_cols = [c for c in df.columns
                if pd.api.types.is_numeric_dtype(df[c]) and c not in ("id", "tahun_akad", "tahun_realisasi", "tenor")]
    for col in num_cols:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) == 0:
            continue
        parts.append(
            f"--- {col.upper()} ---\n"
            f"  Jumlah data: {len(s):,}\n"
            f"  Total: {s.sum():,.2f}\n"
            f"  Rata-rata: {s.mean():,.2f}\n"
            f"  Median: {s.median():,.2f}\n"
            f"  Min: {s.min():,.2f} | Max: {s.max():,.2f}"
        )
        parts.append("")

    # Kolom tahun → distribusi
    for col in ["tahun_akad", "tahun_realisasi", "tenor"]:
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce").dropna().astype(int)
            if len(s) > 0:
                vc = s.value_counts().sort_index()
                pct = (vc / len(s) * 100).round(1)
                rows = [f"  • {k}: {v:,} unit ({p}%)" for (k, v), p in zip(vc.items(), pct)]
                parts.append(f"--- {col.upper()} ---\n" + "\n".join(rows))
                parts.append("")

    return "\n".join(parts)

def ai_analyze(pertanyaan: str, df: pd.DataFrame, total_rows: int,
               stats: dict, plan: dict = None) -> str:
    """AI analisa data hasil query dan jawab pertanyaan user."""

    banks  = ", ".join(stats.get("banks", [])[:20])
    years  = str(stats.get("years", []))
    hint   = (plan or {}).get("answer_hint", "")

    data_summary = build_data_summary(df, total_rows)

    system = f"""Kamu adalah asisten AI ahli data perumahan FLPP (Fasilitas Likuiditas Pembiayaan Perumahan) dari Tapera Indonesia.

=== KONTEKS DATABASE ===
- Total unit FLPP terealisasi: {total_rows:,} unit (ANGKA PASTI)
- Definisi: 1 baris data = 1 unit rumah yang dibiayai FLPP
- Bank pelaksana di data: {banks}
- Rentang tahun: {years}

=== ATURAN MENJAWAB ===
1. Jawab dalam bahasa Indonesia yang natural dan hangat, seperti analis data yang menjelaskan ke teman
2. GUNAKAN angka dari data secara spesifik — sebutkan angka, persentase, perbandingan
3. Untuk pertanyaan "total unit FLPP" → jawabannya PASTI {total_rows:,} unit
4. JANGAN katakan "tidak bisa dipastikan" atau "data tidak cukup" jika angka sudah ada di ringkasan
5. Jika data menunjukkan distribusi per kategori, analisa: mana yang terbesar, terkecil, gap yang menarik
6. Tambahkan insight yang actionable: apa maknanya, apa yang perlu diperhatikan
7. Format: gunakan **angka** untuk highlight, bullet point untuk list, paragraf untuk penjelasan
8. JANGAN sebut "database", "query", "baris", "tabel", "CSV" — bicara seolah kamu yang punya data ini
9. Kalau pertanyaan di luar data (umum tentang FLPP/KPR/perumahan), jawab dari pengetahuanmu{f'''
10. Petunjuk khusus: {hint}''' if hint else ""}"""

    prompt = f"""Pertanyaan: {pertanyaan}

=== RINGKASAN DATA ===
{data_summary}

Jawab pertanyaan di atas secara lengkap, spesifik, dan informatif."""

    return call_groq(
        [{"role": "system", "content": system},
         {"role": "user",   "content": prompt}],
        temperature=0.3,
        max_tokens=1500
    )

# ============================================================
# BUAT GRAFIK
# ============================================================
PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15,23,42,0.8)",
    font=dict(family="Inter", color="#94a3b8", size=12),
    title_font=dict(color="#e2e8f0", size=14),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#334155"),
    margin=dict(t=50, b=40, l=10, r=10),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#94a3b8")),
)
COLORS = ["#38bdf8","#818cf8","#34d399","#fb923c","#f472b6","#a3e635","#facc15","#60a5fa"]

def make_chart(df: pd.DataFrame, plan: dict):
    chart_type  = plan.get("chart_type", "none")
    chart_x     = plan.get("chart_x", "")
    chart_title = plan.get("chart_title", "")

    if chart_type in ("none", "", None) or df.empty:
        return None

    try:
        if chart_type == "histogram" and chart_x in df.columns:
            df[chart_x] = pd.to_numeric(df[chart_x], errors="coerce")
            fig = px.histogram(df.dropna(subset=[chart_x]), x=chart_x,
                               title=chart_title, nbins=30,
                               color_discrete_sequence=["#818cf8"])
            fig.update_layout(**PLOT_LAYOUT)
            return fig

        if chart_x and chart_x in df.columns:
            summary = df.groupby(chart_x).size().reset_index(name="Unit")
            summary[chart_x] = summary[chart_x].astype(str)

            # Tambah agregasi numerik jika ada
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]) and col not in (chart_x, "id"):
                    agg = df.groupby(chart_x)[col].sum().reset_index()
                    summary = summary.merge(agg, on=chart_x, how="left")

            if chart_type == "bar":
                top = summary.nlargest(20, "Unit")
                fig = px.bar(top, x="Unit", y=chart_x, orientation="h",
                             title=chart_title, color="Unit",
                             color_continuous_scale="Blues")
                fig.update_coloraxes(showscale=False)
                fig.update_layout(**PLOT_LAYOUT)
                return fig

            elif chart_type == "pie":
                top = summary.nlargest(10, "Unit")
                fig = px.pie(top, values="Unit", names=chart_x,
                             title=chart_title, hole=0.4,
                             color_discrete_sequence=COLORS)
                fig.update_layout(**PLOT_LAYOUT)
                return fig

            elif chart_type == "line":
                summary[chart_x] = pd.to_numeric(summary[chart_x], errors="coerce")
                summary = summary.dropna(subset=[chart_x]).sort_values(chart_x)
                fig = px.line(summary, x=chart_x, y="Unit",
                              title=chart_title, markers=True,
                              color_discrete_sequence=["#38bdf8"])
                fig.update_traces(line_width=2.5, marker_size=8)
                fig.update_layout(**PLOT_LAYOUT)
                return fig

    except Exception:
        pass
    return None

# ============================================================
# SESSION STATE
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "total" not in st.session_state:
    st.session_state.total = 0
if "stats" not in st.session_state:
    st.session_state.stats = {}
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

# ============================================================
# LOAD STATS — hanya sekali per sesi
# ============================================================
if SUPABASE_KEY and not st.session_state.data_loaded:
    with st.spinner("Menghubungkan ke database..."):
        st.session_state.total = count_total()
        st.session_state.stats = get_stats()
        st.session_state.data_loaded = True

# ============================================================
# HEADER
# ============================================================
st.markdown("""
<div class="app-header">
    <p class="app-title">🏠 Asisten AI Tapera FLPP</p>
    <p class="app-sub">Tanya apa saja tentang data realisasi KPR FLPP Indonesia</p>
</div>
""", unsafe_allow_html=True)

# Status bar
total = st.session_state.total
stats = st.session_state.stats
c1, c2, c3, c4 = st.columns(4)
with c1:
    if total > 0:
        st.markdown(f'<p class="status-ok">✓ Database ({total:,} unit)</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-err">✗ Database tidak terhubung</p>', unsafe_allow_html=True)
with c2:
    st.markdown(
        f'<p class="status-ok">✓ Groq AI aktif</p>' if GROQ_KEY
        else '<p class="status-err">✗ GROQ_KEY kosong</p>',
        unsafe_allow_html=True
    )
with c3:
    banks = stats.get("banks", [])
    st.markdown(
        f'<p class="status-ok">✓ {len(banks)} bank terdeteksi</p>' if banks
        else '<p class="status-err">– Bank belum terbaca</p>',
        unsafe_allow_html=True
    )
with c4:
    years = stats.get("years", [])
    st.markdown(
        f'<p class="status-ok">✓ Tahun {min(years)}–{max(years)}</p>' if years
        else '<p class="status-err">– Tahun belum terbaca</p>',
        unsafe_allow_html=True
    )

st.markdown("---")

# ============================================================
# TAMPILKAN CHAT HISTORY
# ============================================================
if not st.session_state.messages:
    st.markdown("""
    <div class="bubble-wrap">
        <div class="avatar ai">🏠</div>
        <div class="bubble ai">
            Halo! Saya asisten AI untuk data FLPP Tapera.<br><br>
            Saya terhubung langsung ke database realisasi KPR FLPP Indonesia dan bisa membantu Anda menganalisis data — mulai dari statistik nasional, distribusi per wilayah, performa bank, profil pembeli, tren tahunan, hingga analisis pengembang.<br><br>
            Silakan tanya apa saja!
        </div>
    </div>
    """, unsafe_allow_html=True)

for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(f"""
        <div class="bubble-wrap user">
            <div class="avatar user">👤</div>
            <div class="bubble user">{msg["content"]}</div>
        </div>""", unsafe_allow_html=True)
    else:
        # Render markdown dalam bubble — ganti **text** jadi <b>text</b>
        content = msg["content"]
        content = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', content)
        content = content.replace("\n", "<br>")
        st.markdown(f"""
        <div class="bubble-wrap">
            <div class="avatar ai">🏠</div>
            <div class="bubble ai">{content}</div>
        </div>""", unsafe_allow_html=True)

        if msg.get("chart") is not None:
            st.plotly_chart(msg["chart"], use_container_width=True)
        if msg.get("table") is not None and not msg["table"].empty:
            with st.expander(f"📋 Lihat data ({len(msg['table']):,} baris)"):
                st.dataframe(msg["table"], use_container_width=True, hide_index=True)

# ============================================================
# QUICK QUESTIONS (hanya saat chat kosong)
# ============================================================
if not st.session_state.messages:
    st.markdown('<p class="qq-label">💡 Contoh pertanyaan:</p>', unsafe_allow_html=True)
    qq_list = [
        "Berapa total unit FLPP yang sudah terealisasi?",
        "Provinsi mana yang paling banyak unit FLPP?",
        "Bank mana yang paling aktif dalam pembiayaan FLPP?",
        "Bagaimana tren realisasi FLPP per tahun?",
        "Apa profil rata-rata pembeli rumah FLPP?",
        "Pengembang mana yang paling produktif?",
    ]
    cols = st.columns(3)
    for i, q in enumerate(qq_list):
        if cols[i % 3].button(q, key=f"qq{i}", use_container_width=True):
            st.session_state.pending_q = q
            st.rerun()

# ============================================================
# INPUT
# ============================================================
st.markdown("<br>", unsafe_allow_html=True)
col_in, col_btn = st.columns([6, 1])
with col_in:
    user_input = st.text_input(
        "input", placeholder="Ketik pertanyaan tentang data FLPP...",
        label_visibility="collapsed", key="chat_input"
    )
with col_btn:
    send = st.button("Kirim ➤", use_container_width=True)

_, col_reset = st.columns([5, 1])
with col_reset:
    if st.button("🗑️ Reset", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ============================================================
# PROSES PERTANYAAN
# ============================================================
question = None
if send and user_input.strip():
    question = user_input.strip()
elif hasattr(st.session_state, "pending_q"):
    question = st.session_state.pending_q
    del st.session_state.pending_q

if question:
    st.session_state.messages.append({"role": "user", "content": question})

    with st.spinner("🔍 Sedang menganalisis..."):
        _stats = st.session_state.stats or {}
        _total = st.session_state.total

        # STEP 1 — AI buat query plan
        plan = ai_plan_query(question, _stats, _total)

        df_result = pd.DataFrame()
        fig       = None

        # STEP 2 — Jalankan query (kalau perlu)
        if not plan.get("skip_query"):
            # Gunakan count API jika diminta
            if plan.get("use_count_api"):
                count_val = count_with_filter(plan.get("count_filters", {}))
                # Buat df kecil supaya ai_analyze tahu hasilnya
                df_result = pd.DataFrame({"jumlah": [count_val]})
            else:
                df_result = query_supabase(
                    select  = plan.get("select", "*"),
                    filters = plan.get("filters") or None,
                    order   = plan.get("order") or None,
                    limit   = plan.get("limit", 10000),
                )

            # STEP 3 — Buat grafik
            if plan.get("needs_chart") and not df_result.empty:
                fig = make_chart(df_result, plan)

        # STEP 4 — AI analisa & jawab
        jawaban = ai_analyze(question, df_result, _total, _stats, plan=plan)

    # Simpan hasil
    st.session_state.messages.append({
        "role":  "assistant",
        "content": jawaban,
        "chart": fig,
        "table": df_result if (not df_result.empty and len(df_result) <= 300) else None,
    })
    st.rerun()
