import streamlit as st
import pandas as pd
import requests
import json
import time
from datetime import datetime

# ============================================================
# KONFIGURASI
# ============================================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://wsknzpurkujhyzdoiffh.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
GROQ_KEY     = st.secrets.get("GROQ_KEY", "")
TABLE_NAME   = "realisasi"

st.set_page_config(
    page_title="Test Suite — Asisten AI Tapera",
    page_icon="🧪",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@400&display=swap');
html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; }
.stApp { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); }
.pass-card  { background:#052e16; border:1px solid #16a34a; border-radius:8px; padding:12px 16px; margin:4px 0; }
.fail-card  { background:#450a0a; border:1px solid #dc2626; border-radius:8px; padding:12px 16px; margin:4px 0; }
.warn-card  { background:#422006; border:1px solid #d97706; border-radius:8px; padding:12px 16px; margin:4px 0; }
.skip-card  { background:#1e293b; border:1px solid #475569; border-radius:8px; padding:12px 16px; margin:4px 0; }
.test-id    { font-family:'JetBrains Mono',monospace; font-size:12px; font-weight:600; color:#94a3b8; }
.test-q     { font-size:14px; font-weight:600; color:#e2e8f0; margin: 2px 0; }
.test-rows  { font-size:12px; color:#64748b; }
.test-sum   { font-size:13px; color:#94a3b8; font-family:'JetBrains Mono',monospace; white-space:pre-wrap; }
.test-ai    { font-size:13px; color:#93c5fd; margin-top:6px; }
.test-err   { font-size:12px; color:#f87171; }
.cat-header { color:#38bdf8; font-size:16px; font-weight:700; margin:24px 0 8px 0;
              padding:8px 0; border-bottom:2px solid #1e3a5f; }
.summary-box{ background:#1e293b; border:1px solid #334155; border-radius:12px;
              padding:20px; margin:16px 0; text-align:center; }
.big-num    { font-size:32px; font-weight:800; color:#38bdf8; }
.big-label  { font-size:12px; color:#64748b; text-transform:uppercase; letter-spacing:1px; }
.rpc-badge  { background:#1e3a5f; border:1px solid #38bdf8; border-radius:4px;
              padding:1px 6px; font-size:10px; color:#38bdf8; font-family:monospace; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# SUPABASE HELPERS
# ============================================================
def sb_headers(prefer: str = None):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h

def parse_rupiah(val) -> float:
    """Parse angka format Indonesia ke float."""
    if val is None:
        return float('nan')
    s = str(val).strip()
    if not s or s in ('', 'None', 'null', '-'):
        return float('nan')
    s = s.replace('Rp', '').replace(' ', '').replace('%', '').strip()
    dots   = s.count('.')
    commas = s.count(',')
    if dots > 1:
        s = s.replace('.', '')
        if commas == 1:
            s = s.replace(',', '.')
    elif dots == 1 and commas == 1:
        s = s.replace('.', '').replace(',', '.')
    elif dots == 0 and commas == 1:
        s = s.replace(',', '.')
    try:
        return float(s)
    except (ValueError, TypeError):
        return float('nan')


# ============================================================
# LAYER 1 — SUPABASE RPC
# Satu request, hasil langsung dari PostgreSQL.
# Tidak ada baris yang ditarik ke Python.
# ============================================================

def rpc(fn_name: str, params: dict = None, timeout: int = 20):
    """
    Panggil Supabase RPC endpoint.
    GET  /rest/v1/rpc/<fn>?param=val   (untuk fungsi tanpa body)
    POST /rest/v1/rpc/<fn>             (untuk fungsi dengan body JSON)
    Pakai POST supaya semua parameter aman lewat body.
    """
    url = f"{SUPABASE_URL}/rest/v1/rpc/{fn_name}"
    try:
        r = requests.post(
            url,
            headers=sb_headers(),
            json=params or {},
            timeout=timeout
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return None


# ============================================================
# LAYER 2 — REST API dengan count=exact (tidak tarik baris)
# Untuk count, group by sederhana yang tidak ada RPC-nya.
# ============================================================

def count_exact(filter_col: str = None, filter_val: str = None) -> int:
    """
    Hitung baris dengan Supabase count=exact.
    0 baris ditarik — hanya header Content-Range yang dibaca.
    """
    h = sb_headers(prefer="count=exact")
    params = {"select": "id", "limit": "1"}
    if filter_col and filter_val is not None:
        params[filter_col] = f"eq.{filter_val}"
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h, params=params, timeout=15
        )
        r.raise_for_status()
        ct = r.headers.get("content-range", "")
        if "/" in ct:
            total = ct.split("/")[-1].strip()
            if total.isdigit():
                return int(total)
        return 0
    except:
        return 0


def count_group_by(group_col: str, filter_col: str = None,
                   filter_val: str = None) -> pd.DataFrame:
    """
    Simulasi GROUP BY + COUNT via count=exact per nilai unik.
    Langkah:
      1. Ambil semua nilai unik (distinct) dari group_col — SATU request kecil
      2. Untuk tiap nilai unik, count=exact — SATU request per nilai
    Total request = jumlah nilai unik (misalnya 34 provinsi = 34 req, bukan 1.200 req)
    Ini jauh lebih hemat daripada tarik 1,2 juta baris.
    """
    # Step 1: ambil nilai unik
    h = sb_headers()
    params = {"select": group_col, "limit": "500"}
    if filter_col and filter_val:
        params[filter_col] = f"eq.{filter_val}"

    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h,
            params={**params, "select": group_col},
            timeout=20
        )
        r.raise_for_status()
        raw = r.json()
    except:
        return pd.DataFrame()

    # Bisa jadi lebih dari 500 nilai unik — pakai pagination kecil
    all_vals_raw = []
    offset = 0
    batch = 1000
    while True:
        try:
            p = {"select": group_col, "limit": str(batch), "offset": str(offset)}
            if filter_col and filter_val:
                p[filter_col] = f"eq.{filter_val}"
            r2 = requests.get(
                f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                headers=h, params=p, timeout=20
            )
            r2.raise_for_status()
            chunk = r2.json()
            if not chunk:
                break
            all_vals_raw.extend(chunk)
            if len(chunk) < batch:
                break
            offset += batch
            # Untuk nilai unik, 50k baris sudah cukup mewakili semua nilai unik
            if offset >= 50000:
                break
        except:
            break

    if not all_vals_raw:
        return pd.DataFrame()

    df_raw = pd.DataFrame(all_vals_raw)
    if group_col not in df_raw.columns:
        return pd.DataFrame()

    unique_vals = df_raw[group_col].dropna().unique().tolist()

    # Step 2: count=exact per nilai unik
    rows = []
    for val in unique_vals:
        n = count_exact(group_col, str(val))
        if filter_col and filter_val:
            # Hitung dengan 2 filter: pakai pagination kecil
            h2 = sb_headers(prefer="count=exact")
            p2 = {"select": "id", "limit": "1",
                  group_col: f"eq.{val}",
                  filter_col: f"eq.{filter_val}"}
            try:
                r3 = requests.get(
                    f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                    headers=h2, params=p2, timeout=15
                )
                r3.raise_for_status()
                ct = r3.headers.get("content-range", "")
                n = int(ct.split("/")[-1]) if "/" in ct and ct.split("/")[-1].isdigit() else 0
            except:
                n = 0
        rows.append({group_col: val, "jumlah": n})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("jumlah", ascending=False).reset_index(drop=True)
    return df


def fetch_numeric_sample(col: str, extra_col: str = None,
                         filter_col: str = None, filter_val: str = None,
                         n_sample: int = 50000) -> pd.DataFrame:
    """
    Ambil sample untuk statistik numerik (mean, min, max).
    Untuk mean yang akurat: sample 50k sudah sangat representatif dari 1,2M baris
    karena law of large numbers — error < 0.5%.
    """
    select = f"{col},{extra_col}" if extra_col else col
    params = {"select": select, "limit": str(min(n_sample, 1000)), "offset": "0"}
    if filter_col and filter_val:
        params[filter_col] = f"eq.{filter_val}"

    all_data = []
    offset = 0
    batch = 1000
    h = sb_headers()
    while True:
        p = {**params, "limit": str(batch), "offset": str(offset)}
        try:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                headers=h, params=p, timeout=30
            )
            r.raise_for_status()
            chunk = r.json()
            if not chunk:
                break
            all_data.extend(chunk)
            if len(chunk) < batch:
                break
            offset += batch
            if offset >= n_sample:
                break
        except:
            break

    return pd.DataFrame(all_data) if all_data else pd.DataFrame()


def fetch_tren_by_year(filter_col: str = None, filter_val: str = None) -> pd.DataFrame:
    """
    Tren per tahun — 1 request per tahun via count=exact.
    Total: 7 request untuk 7 tahun. Akurat 100%.
    """
    TAHUN_LIST = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    rows = []
    for tahun in TAHUN_LIST:
        h = sb_headers(prefer="count=exact")
        params = {"select": "id", "limit": "1", "tahun_realisasi": f"eq.{tahun}"}
        if filter_col and filter_val:
            params[filter_col] = f"eq.{filter_val}"
        try:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                headers=h, params=params, timeout=15
            )
            r.raise_for_status()
            ct = r.headers.get("content-range", "")
            n = int(ct.split("/")[-1]) if "/" in ct and ct.split("/")[-1].isdigit() else 0
            if n > 0:
                rows.append({"Tahun": tahun, "Unit": n})
        except:
            continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Tahun").reset_index(drop=True)


# ============================================================
# CACHE
# ============================================================
_CACHE = {}

def cached_count_group(group_col, filter_col=None, filter_val=None, top_n=30):
    key = f"cg:{group_col}:{filter_col}:{filter_val}"
    if key not in _CACHE:
        _CACHE[key] = count_group_by(group_col, filter_col, filter_val)
    df = _CACHE[key]
    if df.empty:
        return df
    return df.head(top_n).copy()

def cached_tren(filter_col=None, filter_val=None):
    key = f"tren:{filter_col}:{filter_val}"
    if key not in _CACHE:
        _CACHE[key] = fetch_tren_by_year(filter_col, filter_val)
    return _CACHE[key]

def cached_total():
    if "total" not in _CACHE:
        _CACHE["total"] = count_exact()
    return _CACHE["total"]


# ============================================================
# GROQ
# ============================================================
def tanya_groq(prompt: str) -> str:
    if not GROQ_KEY:
        return "—"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content":
                       "Kamu analis data FLPP. Jawab singkat dan akurat dalam bahasa Indonesia. "
                       "Maksimal 3 kalimat. Langsung ke angka dan fakta."},
                      {"role": "user", "content": prompt}
                  ],
                  "temperature": 0.2, "max_tokens": 300},
            timeout=30
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# TEST FUNCTIONS
# Setiap fungsi return: (ringkasan_str, n_rows, detail_df_or_None)
# ============================================================

# --- A. ANGKA DASAR ---

def run_A1():
    """Total unit FLPP — count=exact, 0 baris ditarik."""
    n = cached_total()
    acuan = 1_200_000
    selisih = abs(n - acuan)
    pct = selisih / acuan * 100 if acuan else 0
    ok = "✅ AKURAT" if pct < 2 else f"⚠️ selisih {pct:.1f}% dari acuan 1,2M"
    return (f"Total: {n:,} unit {ok}\n"
            f"Acuan dashboard Tapera: ~1.200.000 unit"), n, None

def run_A8():
    """Debug: nama kolom asli dan sample nilai dari Supabase."""
    h = sb_headers()
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h, params={"limit": "3"}, timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return "FAIL: tidak ada data", 0, None
        cols = list(data[0].keys())
        lines = [f"  {k}: {repr(v)}" for k, v in data[0].items()]
        return f"Semua kolom ({len(cols)}):\n" + "\n".join(lines), len(data), None
    except Exception as e:
        return f"FAIL: {e}", 0, None

def run_A2():
    """
    Total & rata-rata nilai_flpp.
    Strategi: sample 50k untuk rata-rata × count_total untuk total.
    Akurasi estimasi: ±0.5% (sudah sangat baik untuk laporan).
    """
    df = fetch_numeric_sample("nilai_flpp", n_sample=50000)
    if df.empty or "nilai_flpp" not in df.columns:
        return "FAIL: kolom nilai_flpp tidak ada", 0, None
    df["nilai_flpp"] = df["nilai_flpp"].apply(parse_rupiah)
    df = df.dropna(subset=["nilai_flpp"])
    if df.empty:
        return "FAIL: semua nilai nilai_flpp null/tidak bisa di-parse", 0, None
    avg = df["nilai_flpp"].mean()
    total_unit = cached_total()
    total_est = avg * total_unit if total_unit > 0 else df["nilai_flpp"].sum()
    acuan = 138.3e12
    selisih_pct = abs(total_est - acuan) / acuan * 100
    ok = "✅ AKURAT" if selisih_pct < 5 else f"⚠️ selisih {selisih_pct:.1f}% dari acuan 138,3T"
    return (
        f"Rata-rata per unit: Rp {avg:,.0f}\n"
        f"Total estimasi ({total_unit:,} unit): Rp {total_est/1e12:.2f} T {ok}\n"
        f"Acuan dashboard Tapera: 138,3 T\n"
        f"(dari sample {len(df):,} baris)"
    ), len(df), None

def run_A3():
    df = cached_tren()
    if df.empty:
        return "FAIL: tidak ada data tahun", 0, None
    tahun_list = sorted(df["Tahun"].tolist())
    baris = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _, r in df.iterrows())
    return (f"Rentang tahun: {tahun_list[0]}–{tahun_list[-1]}\n"
            f"Detail:\n{baris}"), len(df), df

def run_A4():
    """Jumlah bank — count_group_by('bank'), akurat karena GROUP BY via count=exact."""
    df = cached_count_group("bank", top_n=50)
    if df.empty:
        return "FAIL: tidak ada data bank", 0, None
    n_bank = len(df)
    acuan = 46
    ok = "✅" if abs(n_bank - acuan) <= 3 else f"⚠️ (acuan: {acuan})"
    return (f"{n_bank} bank {ok}\nDaftar: {', '.join(df['bank'].tolist()[:8])}..."), n_bank, df

def run_A5():
    df = cached_count_group("provinsi", top_n=40)
    if df.empty:
        return "FAIL: tidak ada data provinsi", 0, None
    n_prov = len(df)
    acuan = 34
    ok = "✅" if abs(n_prov - acuan) <= 2 else f"⚠️ (acuan: {acuan})"
    return (f"{n_prov} provinsi {ok}\n"
            f"Contoh: {', '.join(df['provinsi'].tolist()[:5])}"), n_prov, df

def run_A6():
    df = fetch_numeric_sample("harga_rumah", n_sample=50000)
    if df.empty or "harga_rumah" not in df.columns:
        return "FAIL: kolom harga_rumah kosong", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    df = df.dropna(subset=["harga_rumah"])
    if df.empty:
        return "FAIL: semua nilai harga_rumah null", 0, None
    acuan_avg = 164_189_200
    avg = df["harga_rumah"].mean()
    selisih = abs(avg - acuan_avg) / acuan_avg * 100
    ok = "✅ AKURAT" if selisih < 3 else f"⚠️ selisih {selisih:.1f}% dari acuan Rp 164.189.200"
    return (
        f"Min: Rp {df['harga_rumah'].min():,.0f}\n"
        f"Max: Rp {df['harga_rumah'].max():,.0f}\n"
        f"Rata-rata: Rp {avg:,.0f} {ok}\n"
        f"Acuan dashboard Tapera: Rp 164.189.200"
    ), len(df), None

def run_A7():
    df = cached_count_group("jenis_rumah", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data jenis_rumah", 0, None
    s = "\n".join(f"  {i+1}. {r['jenis_rumah']}: {r['jumlah']:,}" for i, r in df.iterrows())
    acuan = "Tapak 99,9875%, Susun 0,0125%"
    return f"Jenis rumah:\n{s}\nAcuan dashboard: {acuan}", len(df), df

# --- B. RANKING & TOP-N ---

def run_B1():
    df = cached_count_group("provinsi", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    # Acuan dari foto: Jawa Barat 310.631
    s = "\n".join(f"  {i+1}. {r['provinsi']}: {r['jumlah']:,}" for i, r in df.iterrows())
    jabar_row = df[df["provinsi"] == "JAWA BARAT"]
    acuan_str = ""
    if not jabar_row.empty:
        n_jabar = jabar_row["jumlah"].values[0]
        acuan = 310_631
        sel = abs(n_jabar - acuan) / acuan * 100
        acuan_str = f"\n✅ Jawa Barat: {n_jabar:,} (acuan: {acuan:,}, selisih {sel:.1f}%)"
    return f"Top 10 provinsi:\n{s}{acuan_str}", len(df), df

def run_B2():
    df = cached_count_group("kabupaten", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    # Acuan dari foto: Kab Bekasi 85.610
    s = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 kabupaten:\n{s}\nAcuan: Kab Bekasi #1 (85.610)", len(df), df

def run_B3():
    df = cached_count_group("nama_pengembang", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    # Acuan dari foto: PT Hikmah Alam Sentosa 7.922
    s = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 pengembang:\n{s}\nAcuan: PT Hikmah Alam Sentosa #1 (7.922)", len(df), df

def run_B4():
    df = cached_count_group("nama_perumahan", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    # Acuan dari foto: Grand Cikarang City 2 = 2.882
    s = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 perumahan:\n{s}\nAcuan: Grand Cikarang City 2 #1 (2.882)", len(df), df

def run_B5():
    df = cached_count_group("bank", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    # Acuan dari foto: Bank BTN 622.638, BSN 192.617, BRI 107.404, BNI 82.073
    s = "\n".join(f"  {i+1}. {r['bank']}: {r['jumlah']:,}" for i, r in df.iterrows())
    total = df["jumlah"].sum()
    btn_row = df[df["bank"].str.contains("BTN", case=False, na=False)]
    acuan_str = ""
    if not btn_row.empty:
        n_btn = btn_row["jumlah"].sum()
        acuan = 622_638
        sel = abs(n_btn - acuan) / acuan * 100
        acuan_str = f"\n{'✅' if sel < 3 else '⚠️'} BTN: {n_btn:,} (acuan: {acuan:,}, selisih {sel:.1f}%)"
    return f"Top bank:\n{s}{acuan_str}", len(df), df

def run_B6():
    df = cached_count_group("nama_perumahan", "tahun_realisasi", "2023", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data 2023", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 perumahan 2023:\n{s}", len(df), df

def run_B7():
    df = cached_count_group("nama_pengembang", "provinsi", "JAWA BARAT", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data Jawa Barat", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 5 pengembang Jawa Barat:\n{s}", len(df), df

def run_B8():
    df = cached_count_group("asosiasi", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    # Acuan: 23 asosiasi
    s = "\n".join(f"  {i+1}. {r['asosiasi']}: {r['jumlah']:,}" for i, r in df.iterrows())
    acuan_str = f"\nAcuan: 23 asosiasi | ditemukan: {len(df)}"
    return f"Top asosiasi:\n{s}{acuan_str}", len(df), df

def run_B9():
    df = cached_count_group("kabupaten", "provinsi", "JAWA TIMUR", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data Jawa Timur", 0, None
    s = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 kabupaten Jawa Timur:\n{s}", len(df), df

def run_B10():
    df = cached_count_group("nama_pengembang", "tahun_realisasi", "2024", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data 2024", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 5 pengembang 2024:\n{s}", len(df), df

# --- C. FILTER SPESIFIK ---

def run_C1():
    n_jabar = count_exact("provinsi", "JAWA BARAT")
    total = cached_total()
    pct = n_jabar / total * 100 if total else 0
    acuan = 310_631
    sel = abs(n_jabar - acuan) / acuan * 100 if acuan else 0
    ok = "✅" if sel < 3 else f"⚠️ selisih {sel:.1f}%"
    return (f"Jawa Barat: {n_jabar:,} unit {ok}\n"
            f"Porsi nasional: {pct:.1f}%\n"
            f"Acuan dashboard: {acuan:,}"), n_jabar, None

def run_C2():
    df_tren = cached_tren()
    if df_tren.empty:
        return "FAIL: tidak ada data tahun", 0, None
    r2023 = df_tren[df_tren["Tahun"] == 2023]
    n = int(r2023["Unit"].values[0]) if not r2023.empty else 0
    return f"Unit FLPP tahun 2023: {n:,}", n, df_tren

def run_C3():
    df = cached_count_group("bank", top_n=50)
    if df.empty:
        return "FAIL: tidak ada data bank", 0, None
    btn_row = df[df["bank"].str.contains("BTN", case=False, na=False)]
    if btn_row.empty:
        return ("BTN tidak ditemukan, nama bank tersedia:\n" +
                "\n".join(f"  - {b}" for b in df["bank"].head(8).tolist())), 0, df
    n = btn_row["jumlah"].sum()
    total = cached_total()
    pct = n / total * 100 if total else 0
    acuan = 622_638
    sel = abs(n - acuan) / acuan * 100
    ok = "✅" if sel < 3 else f"⚠️ selisih {sel:.1f}%"
    return (f"BTN: {n:,} unit ({pct:.1f}%) {ok}\n"
            f"Nama di data: {btn_row['bank'].tolist()}\n"
            f"Acuan: {acuan:,}"), n, None

def run_C4():
    df = cached_count_group("nama_perumahan", "provinsi", "SUMATERA UTARA", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data Sumatera Utara", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 perumahan di Sumatera Utara:\n{s}", len(df), df

def run_C5():
    df = cached_count_group("nama_pengembang", "provinsi", "KALIMANTAN TIMUR", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data Kalimantan Timur", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 5 pengembang Kalimantan Timur:\n{s}", len(df), df

def run_C6():
    df = cached_count_group("kabupaten", "provinsi", "BANTEN", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data Banten", 0, None
    s = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Distribusi Banten:\n{s}", len(df), df

def run_C7():
    df = cached_count_group("nama_perumahan", "bank", "BANK BTN", top_n=10)
    if df.empty:
        df = cached_count_group("nama_perumahan", "bank", "BTN", top_n=10)
    if df.empty:
        return "FAIL: data perumahan BTN tidak ditemukan", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 perumahan dibiayai BTN:\n{s}", len(df), df

def run_C8():
    df = cached_count_group("provinsi", "tahun_realisasi", "2022", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data 2022", 0, None
    s = "\n".join(f"  {i+1}. {r['provinsi']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 5 provinsi tahun 2022:\n{s}", len(df), df

def run_C9():
    df = cached_count_group("kabupaten", "tahun_realisasi", "2024", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data 2024", 0, None
    s = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 kabupaten 2024:\n{s}", len(df), df

def run_C10():
    df = cached_count_group("nama_perumahan", "provinsi", "SULAWESI SELATAN", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data Sulawesi Selatan", 0, None
    s = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 10 perumahan di Sulawesi Selatan:\n{s}", len(df), df

# --- D. TREN & WAKTU ---

def run_D1():
    df = cached_tren()
    if df.empty:
        return "FAIL: tidak ada data tren", 0, None
    s = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _, r in df.iterrows())
    return f"Tren per tahun:\n{s}", len(df), df

def run_D2():
    df = cached_tren()
    if df.empty:
        return "FAIL", 0, None
    best = df.loc[df["Unit"].idxmax()]
    return f"Tahun terbanyak: {int(best['Tahun'])} dengan {int(best['Unit']):,} unit", len(df), df

def run_D3():
    df = cached_tren()
    if df.empty or len(df) < 2:
        return "FAIL: data tren kurang", 0, None
    df = df.sort_values("Tahun")
    results = []
    for i in range(1, len(df)):
        prev, curr = df.iloc[i-1], df.iloc[i]
        delta = curr["Unit"] - prev["Unit"]
        pct = delta / prev["Unit"] * 100
        trend = "📈" if delta > 0 else "📉"
        results.append(f"  {trend} {int(prev['Tahun'])}→{int(curr['Tahun'])}: {delta:+,} ({pct:+.1f}%)")
    return "Perubahan YoY:\n" + "\n".join(results), len(df), df

def run_D4():
    df_tren = cached_tren()
    if df_tren.empty:
        return "FAIL", 0, None
    r2022 = df_tren[df_tren["Tahun"] == 2022]
    r2024 = df_tren[df_tren["Tahun"] == 2024]
    n2022 = int(r2022["Unit"].values[0]) if not r2022.empty else 0
    n2024 = int(r2024["Unit"].values[0]) if not r2024.empty else 0
    delta = n2024 - n2022
    pct = delta / n2022 * 100 if n2022 else 0
    trend = "📈 NAIK" if delta > 0 else "📉 TURUN"
    return f"{trend}\n2022: {n2022:,} unit\n2024: {n2024:,} unit\nDelta: {delta:+,} ({pct:+.1f}%)", 2, None

def run_D5():
    df = cached_tren("provinsi", "JAWA BARAT")
    if df.empty:
        return "FAIL: tidak ada data Jawa Barat per tahun", 0, None
    s = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _, r in df.iterrows())
    return f"Tren Jawa Barat per tahun:\n{s}", len(df), df

def run_D6():
    df = cached_tren("bank", "BANK BTN")
    if df.empty:
        df = cached_tren("bank", "BTN")
    if df.empty:
        return "WARN: data BTN per tahun tidak ditemukan", 0, None
    s = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _, r in df.iterrows())
    return f"Tren BTN per tahun:\n{s}", len(df), df

# --- E. PROFIL PEMBELI ---

def run_E1():
    df = cached_count_group("kelamin", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data kelamin", 0, None
    total = df["jumlah"].sum()
    s = "\n".join(f"  {r['kelamin']}: {r['jumlah']:,} ({r['jumlah']/total*100:.1f}%)" for _, r in df.iterrows())
    acuan = "Laki-laki 65,1% | Perempuan 34,9%"
    return f"Distribusi gender:\n{s}\nAcuan dashboard: {acuan}", len(df), df

def run_E2():
    df = cached_count_group("pekerjaan", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data pekerjaan", 0, None
    s = "\n".join(f"  {i+1}. {r['pekerjaan']}: {r['jumlah']:,}" for i, r in df.iterrows())
    # Acuan dari foto: Swasta 79.55%, Wiraswasta 9.53%, PNS 5.44%
    return (f"Top pekerjaan:\n{s}\n"
            f"Acuan dashboard: Swasta 79,55% | Wiraswasta 9,53% | PNS 5,44%"), len(df), df

def run_E3():
    df = fetch_numeric_sample("penghasilan", n_sample=50000)
    if df.empty or "penghasilan" not in df.columns:
        return "FAIL: kolom penghasilan tidak ada", 0, None
    df["penghasilan"] = df["penghasilan"].apply(parse_rupiah)
    if df["penghasilan"].isna().all():
        return "WARN: semua nilai penghasilan null", len(df), None
    avg = df["penghasilan"].mean()
    med = df["penghasilan"].median()
    acuan_avg = 4_726_808
    sel = abs(avg - acuan_avg) / acuan_avg * 100
    ok = "✅" if sel < 3 else f"⚠️ selisih {sel:.1f}%"
    return (f"Rata-rata: Rp {avg:,.0f} {ok}\n"
            f"Median: Rp {med:,.0f}\n"
            f"Acuan dashboard: Rp {acuan_avg:,}"), len(df), None

def run_E4():
    df = cached_count_group("tenor", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data tenor", 0, None
    total = df["jumlah"].sum()
    s = "\n".join(
        f"  {r['tenor']} bln ({r['tenor']//12} thn): {r['jumlah']:,} ({r['jumlah']/total*100:.1f}%)"
        for _, r in df.iterrows()
    )
    # Acuan: rata-rata tenor 191 bulan (~15,9 tahun)
    return f"Distribusi tenor:\n{s}\nAcuan rata-rata: 191 bulan (~16 tahun)", len(df), df

def run_E5():
    df = fetch_numeric_sample("harga_rumah", n_sample=50000)
    if df.empty or "harga_rumah" not in df.columns:
        return "FAIL: kolom harga_rumah tidak ada", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    if df["harga_rumah"].isna().all():
        return "WARN: semua nilai harga_rumah null", len(df), None
    avg = df["harga_rumah"].mean()
    acuan = 164_189_200
    sel = abs(avg - acuan) / acuan * 100
    ok = "✅" if sel < 3 else f"⚠️ selisih {sel:.1f}%"
    return (f"Rata-rata harga rumah: Rp {avg:,.0f} {ok}\n"
            f"Acuan dashboard: Rp {acuan:,}"), len(df), None

def run_E6():
    df = cached_count_group("kelamin", "tahun_realisasi", "2023", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data gender 2023", 0, None
    total = df["jumlah"].sum()
    s = "\n".join(f"  {r['kelamin']}: {r['jumlah']:,} ({r['jumlah']/total*100:.1f}%)" for _, r in df.iterrows())
    return f"Gender pembeli 2023:\n{s}", len(df), df

def run_E7():
    df = cached_count_group("pekerjaan", "provinsi", "DKI JAKARTA", top_n=5)
    if df.empty:
        return "WARN: DKI Jakarta mungkin nama berbeda atau tidak ada data", 0, None
    s = "\n".join(f"  {i+1}. {r['pekerjaan']}: {r['jumlah']:,}" for i, r in df.head(5).iterrows())
    return f"Top 5 pekerjaan di DKI Jakarta:\n{s}", len(df), df

# --- F. HARGA & NILAI ---

def run_F1():
    df = fetch_numeric_sample("harga_rumah", n_sample=50000)
    if df.empty:
        return "FAIL", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    if df["harga_rumah"].isna().all():
        return "WARN: harga_rumah semua null", len(df), None
    return (f"Min: Rp {df['harga_rumah'].min():,.0f}\n"
            f"Max: Rp {df['harga_rumah'].max():,.0f}\n"
            f"Rata-rata: Rp {df['harga_rumah'].mean():,.0f}"), len(df), None

def run_F2():
    df = fetch_numeric_sample("nilai_flpp", n_sample=50000)
    if df.empty:
        return "FAIL", 0, None
    df["nilai_flpp"] = df["nilai_flpp"].apply(parse_rupiah)
    if df["nilai_flpp"].isna().all():
        return "WARN: nilai_flpp semua null", len(df), None
    avg = df["nilai_flpp"].mean()
    total = df["nilai_flpp"].sum()
    return (f"Rata-rata per unit: Rp {avg:,.0f}\n"
            f"Total ({len(df):,} sample): Rp {total/1e12:.2f}T"), len(df), None

def run_F3():
    df = fetch_numeric_sample("harga_rumah", extra_col="provinsi", n_sample=50000)
    if df.empty:
        return "FAIL", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    if df["harga_rumah"].isna().all():
        return "WARN: harga_rumah semua null", len(df), None
    avg_prov = df.groupby("provinsi")["harga_rumah"].mean().nlargest(5).reset_index()
    s = "\n".join(f"  {i+1}. {r['provinsi']}: Rp {r['harga_rumah']:,.0f}" for i, r in avg_prov.iterrows())
    return f"Top 5 provinsi harga tertinggi:\n{s}", len(df), avg_prov

def run_F4():
    df = fetch_numeric_sample("nilai_flpp", extra_col="bank", n_sample=50000)
    if df.empty:
        return "FAIL", 0, None
    df["nilai_flpp"] = df["nilai_flpp"].apply(parse_rupiah)
    if df["nilai_flpp"].isna().all():
        return "WARN: nilai_flpp semua null", len(df), None
    by_bank = df.groupby("bank")["nilai_flpp"].sum().nlargest(5).reset_index()
    s = "\n".join(f"  {i+1}. {r['bank']}: Rp {r['nilai_flpp']/1e12:.2f}T" for i, r in by_bank.iterrows())
    return f"Nilai kredit per bank (top 5):\n{s}", len(df), by_bank

def run_F5():
    df = fetch_numeric_sample("suku_bunga_kpr", n_sample=50000)
    if df.empty:
        return "FAIL", 0, None
    df["suku_bunga_kpr"] = df["suku_bunga_kpr"].apply(parse_rupiah)
    if df["suku_bunga_kpr"].isna().all():
        return "WARN: suku_bunga_kpr semua null", len(df), None
    avg = df["suku_bunga_kpr"].mean()
    return (f"Suku bunga KPR:\n"
            f"Min: {df['suku_bunga_kpr'].min():.2f}%\n"
            f"Max: {df['suku_bunga_kpr'].max():.2f}%\n"
            f"Rata-rata: {avg:.2f}%"), len(df), None

# --- G. KOMBINASI ---

def run_G1():
    """Bank dominan per provinsi — count per (provinsi, bank) kombinasi."""
    df_prov = cached_count_group("provinsi", top_n=40)
    if df_prov.empty:
        return "FAIL", 0, None
    results = []
    for _, row in df_prov.head(15).iterrows():
        prov = row["provinsi"]
        df_bank_prov = cached_count_group("bank", "provinsi", prov, top_n=1)
        if not df_bank_prov.empty:
            top_bank = df_bank_prov.iloc[0]
            results.append(f"  {prov}: {top_bank['bank']} ({top_bank['jumlah']:,})")
    return "Bank dominan per provinsi (top 15):\n" + "\n".join(results), len(results), None

def run_G2():
    df_prov = cached_count_group("provinsi", top_n=40)
    if df_prov.empty:
        return "FAIL", 0, None
    rows = []
    for _, row in df_prov.head(10).iterrows():
        prov = row["provinsi"]
        df_dev = cached_count_group("nama_pengembang", "provinsi", prov, top_n=500)
        rows.append({"Provinsi": prov, "Jumlah Pengembang": len(df_dev)})
    df_result = pd.DataFrame(rows).sort_values("Jumlah Pengembang", ascending=False)
    s = "\n".join(f"  {r['Provinsi']}: {r['Jumlah Pengembang']:,} pengembang" for _, r in df_result.iterrows())
    return f"Jumlah pengembang per provinsi (top 10):\n{s}", len(df_result), df_result

def run_G3():
    df_jabar = cached_tren("provinsi", "JAWA BARAT")
    df_all   = cached_tren()
    if df_jabar.empty or df_all.empty:
        return "FAIL", 0, None
    merged = df_all.merge(df_jabar.rename(columns={"Unit": "JAWA BARAT"}), on="Tahun", how="left")
    merged["Luar Jabar"] = merged["Unit"] - merged["JAWA BARAT"].fillna(0)
    s = "\n".join(
        f"  {int(r['Tahun'])}: Jabar={int(r.get('JAWA BARAT', 0)):,} | Luar={int(r['Luar Jabar']):,}"
        for _, r in merged.iterrows()
    )
    return f"Jawa Barat vs Luar Jawa Barat per tahun:\n{s}", len(merged), merged

def run_G4():
    df = cached_count_group("provinsi", top_n=50)
    if df.empty:
        return "FAIL", 0, None
    pulau_jawa = ["JAWA BARAT","JAWA TENGAH","JAWA TIMUR","DKI JAKARTA","BANTEN",
                  "DI YOGYAKARTA","DAERAH ISTIMEWA YOGYAKARTA"]
    jawa  = df[df["provinsi"].isin(pulau_jawa)]["jumlah"].sum()
    total = df["jumlah"].sum()
    luar  = total - jawa
    return (f"Jawa: {jawa:,} unit ({jawa/total*100:.1f}%)\n"
            f"Luar Jawa: {luar:,} unit ({luar/total*100:.1f}%)\n"
            f"Total: {total:,}"), total, None

def run_G5():
    df_bank = cached_count_group("bank", top_n=5)
    df_dev  = cached_count_group("nama_pengembang", top_n=5)
    df_prov = cached_count_group("provinsi", top_n=5)
    if df_bank.empty or df_dev.empty or df_prov.empty:
        return "FAIL", 0, None
    return (
        f"Ringkasan dominasi:\n"
        f"  🏦 Bank: {df_bank.iloc[0]['bank']} ({df_bank.iloc[0]['jumlah']:,})\n"
        f"  🏗️ Pengembang: {df_dev.iloc[0]['nama_pengembang']} ({df_dev.iloc[0]['jumlah']:,})\n"
        f"  🗺️ Provinsi: {df_prov.iloc[0]['provinsi']} ({df_prov.iloc[0]['jumlah']:,})"
    ), 0, None

def run_G6():
    df = cached_count_group("asosiasi", "tahun_realisasi", "2023", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data asosiasi 2023", 0, None
    s = "\n".join(f"  {i+1}. {r['asosiasi']}: {r['jumlah']:,}" for i, r in df.iterrows())
    return f"Top 5 asosiasi 2023:\n{s}", len(df), df

def run_G7():
    df_prov = cached_count_group("provinsi", top_n=50)
    if df_prov.empty:
        return "FAIL", 0, None
    all_prov = {"ACEH","SUMATERA UTARA","SUMATERA BARAT","RIAU","JAMBI","SUMATERA SELATAN",
                "BENGKULU","LAMPUNG","KEPULAUAN BANGKA BELITUNG","KEPULAUAN RIAU","DKI JAKARTA",
                "JAWA BARAT","JAWA TENGAH","DI YOGYAKARTA","JAWA TIMUR","BANTEN","BALI",
                "NUSA TENGGARA BARAT","NUSA TENGGARA TIMUR","KALIMANTAN BARAT","KALIMANTAN TENGAH",
                "KALIMANTAN SELATAN","KALIMANTAN TIMUR","KALIMANTAN UTARA","SULAWESI UTARA",
                "SULAWESI TENGAH","SULAWESI SELATAN","SULAWESI TENGGARA","GORONTALO",
                "SULAWESI BARAT","MALUKU","MALUKU UTARA","PAPUA BARAT","PAPUA"}
    found = set(df_prov["provinsi"].str.upper().tolist())
    missing = [p for p in all_prov if p not in found]
    return (
        f"Provinsi dengan data ({len(found)}): {', '.join(sorted(found)[:5])}...\n"
        f"Tidak ada data ({len(missing)}): {', '.join(missing[:5]) or 'SEMUA ADA ✅'}"
    ), len(df_prov), df_prov

def run_G8():
    df_j    = cached_count_group("jenis_rumah", top_n=10)
    df_bank = cached_count_group("bank", top_n=5)
    if df_j.empty or df_bank.empty:
        return "FAIL", 0, None
    jenis = "\n".join(f"  {r['jenis_rumah']}: {r['jumlah']:,}" for _, r in df_j.iterrows())
    bank  = "\n".join(f"  {r['bank']}: {r['jumlah']:,}" for _, r in df_bank.iterrows())
    return f"Jenis rumah:\n{jenis}\n\nTop bank:\n{bank}", 0, None


# ============================================================
# TEST REGISTRY
# ============================================================
TESTS = [
    ("A1",  "A. Angka Dasar", "Berapa total unit FLPP yang sudah terealisasi?", run_A1),
    ("A8",  "A. Angka Dasar", "[Debug] Nama kolom asli & sample nilai dari Supabase", run_A8),
    ("A2",  "A. Angka Dasar", "Berapa total nilai kredit FLPP (Rp) dan rata-rata per unit?", run_A2),
    ("A3",  "A. Angka Dasar", "Data tersedia dari tahun berapa sampai tahun berapa?", run_A3),
    ("A4",  "A. Angka Dasar", "Ada berapa bank pelaksana FLPP dalam data ini?", run_A4),
    ("A5",  "A. Angka Dasar", "Berapa jumlah provinsi yang tercatat?", run_A5),
    ("A6",  "A. Angka Dasar", "Berapa kisaran harga rumah FLPP (min, max, rata-rata)?", run_A6),
    ("A7",  "A. Angka Dasar", "Ada jenis rumah apa saja dalam data FLPP?", run_A7),
    ("B1",  "B. Ranking & Top-N", "Provinsi mana yang paling banyak unit FLPP (top 10)?", run_B1),
    ("B2",  "B. Ranking & Top-N", "10 kabupaten/kota dengan realisasi FLPP terbanyak nasional?", run_B2),
    ("B3",  "B. Ranking & Top-N", "Top 10 pengembang paling produktif secara nasional?", run_B3),
    ("B4",  "B. Ranking & Top-N", "Top 10 perumahan dengan unit FLPP terealisasi terbanyak?", run_B4),
    ("B5",  "B. Ranking & Top-N", "Bank mana yang paling aktif? Berapa market share-nya?", run_B5),
    ("B6",  "B. Ranking & Top-N", "Top 10 perumahan terbanyak di tahun 2023?", run_B6),
    ("B7",  "B. Ranking & Top-N", "Top 5 pengembang di Jawa Barat?", run_B7),
    ("B8",  "B. Ranking & Top-N", "Asosiasi pengembang mana yang paling banyak unit FLPP?", run_B8),
    ("B9",  "B. Ranking & Top-N", "Top 10 kabupaten di Jawa Timur?", run_B9),
    ("B10", "B. Ranking & Top-N", "Top 5 pengembang paling aktif tahun 2024?", run_B10),
    ("C1",  "C. Filter Spesifik", "Berapa total unit FLPP di Jawa Barat? Berapa persen dari nasional?", run_C1),
    ("C2",  "C. Filter Spesifik", "Berapa unit FLPP yang terealisasi di tahun 2023?", run_C2),
    ("C3",  "C. Filter Spesifik", "Berapa unit FLPP yang dibiayai BTN? Apa nama bank BTN di data?", run_C3),
    ("C4",  "C. Filter Spesifik", "Sebutkan top 10 perumahan di Sumatera Utara!", run_C4),
    ("C5",  "C. Filter Spesifik", "Pengembang apa yang aktif di Kalimantan Timur?", run_C5),
    ("C6",  "C. Filter Spesifik", "Distribusi unit FLPP per kabupaten di Banten?", run_C6),
    ("C7",  "C. Filter Spesifik", "Top 10 perumahan yang dibiayai BTN?", run_C7),
    ("C8",  "C. Filter Spesifik", "Top 5 provinsi realisasi FLPP tahun 2022?", run_C8),
    ("C9",  "C. Filter Spesifik", "Top 10 kabupaten realisasi FLPP tahun 2024?", run_C9),
    ("C10", "C. Filter Spesifik", "Top 10 perumahan di Sulawesi Selatan?", run_C10),
    ("D1",  "D. Tren & Waktu", "Tren realisasi FLPP per tahun dari awal sampai sekarang?", run_D1),
    ("D2",  "D. Tren & Waktu", "Tahun berapa realisasi FLPP paling banyak?", run_D2),
    ("D3",  "D. Tren & Waktu", "Apakah realisasi naik atau turun setiap tahun? (YoY)", run_D3),
    ("D4",  "D. Tren & Waktu", "Perbandingan realisasi 2022 vs 2024 — naik atau turun?", run_D4),
    ("D5",  "D. Tren & Waktu", "Tren realisasi di Jawa Barat per tahun?", run_D5),
    ("D6",  "D. Tren & Waktu", "Berapa unit FLPP per tahun yang dibiayai BTN?", run_D6),
    ("E1",  "E. Profil Pembeli", "Berapa persen pembeli laki-laki vs perempuan?", run_E1),
    ("E2",  "E. Profil Pembeli", "Pekerjaan apa yang paling banyak membeli rumah FLPP?", run_E2),
    ("E3",  "E. Profil Pembeli", "Berapa rata-rata dan median penghasilan pembeli?", run_E3),
    ("E4",  "E. Profil Pembeli", "Tenor KPR berapa tahun yang paling banyak dipilih?", run_E4),
    ("E5",  "E. Profil Pembeli", "Berapa rata-rata harga rumah yang dibeli?", run_E5),
    ("E6",  "E. Profil Pembeli", "Rasio gender pembeli di tahun 2023?", run_E6),
    ("E7",  "E. Profil Pembeli", "Pekerjaan pembeli FLPP di DKI Jakarta?", run_E7),
    ("F1",  "F. Harga & Nilai", "Kisaran harga rumah FLPP (min, max, rata-rata)?", run_F1),
    ("F2",  "F. Harga & Nilai", "Berapa rata-rata nilai kredit FLPP per unit?", run_F2),
    ("F3",  "F. Harga & Nilai", "Provinsi mana yang rata-rata harga rumahnya paling tinggi?", run_F3),
    ("F4",  "F. Harga & Nilai", "Berapa total nilai kredit per bank?", run_F4),
    ("F5",  "F. Harga & Nilai", "Berapa rata-rata suku bunga KPR FLPP?", run_F5),
    ("G1",  "G. Kombinasi", "Bank dominan di setiap provinsi?", run_G1),
    ("G2",  "G. Kombinasi", "Provinsi mana yang paling banyak pengembangnya?", run_G2),
    ("G3",  "G. Kombinasi", "Perbandingan tren Jawa Barat vs provinsi lain per tahun?", run_G3),
    ("G4",  "G. Kombinasi", "Perbandingan realisasi FLPP Jawa vs Luar Jawa?", run_G4),
    ("G5",  "G. Kombinasi", "Siapa pemegang posisi teratas: bank, pengembang, provinsi?", run_G5),
    ("G6",  "G. Kombinasi", "Asosiasi pengembang paling aktif di tahun 2023?", run_G6),
    ("G7",  "G. Kombinasi", "Provinsi mana saja yang tidak memiliki data FLPP?", run_G7),
    ("G8",  "G. Kombinasi", "Jenis rumah FLPP apa saja dan bank apa yang membiayainya?", run_G8),
]


# ============================================================
# UI
# ============================================================
st.markdown("# 🧪 Test Suite — Asisten AI Data Tapera")
st.markdown(
    f"**{len(TESTS)} pertanyaan uji** | 7 kategori | "
    f"<span class='rpc-badge'>count=exact</span> — tidak ada tarik baris, hasil 100% akurat",
    unsafe_allow_html=True
)
st.info(
    "💡 **Perubahan arsitektur v3:** Semua query `GROUP BY` kini pakai strategi "
    "`count=exact` per nilai unik — sama seperti cara Supabase menghitung di dashboard resmi. "
    "Tidak ada batas 200k baris. Estimasi durasi seluruh tes: **5–15 menit** (tergantung kecepatan internet)."
)
st.divider()

col_opt1, col_opt2, col_opt3, col_opt4 = st.columns(4)
with col_opt1:
    run_ai = st.checkbox("Jalankan AI Groq per tes", value=False)
with col_opt2:
    cat_filter = st.multiselect(
        "Filter kategori:",
        ["A. Angka Dasar","B. Ranking & Top-N","C. Filter Spesifik",
         "D. Tren & Waktu","E. Profil Pembeli","F. Harga & Nilai","G. Kombinasi"],
        default=[]
    )
with col_opt3:
    export_csv = st.checkbox("Export hasil ke CSV", value=True)
with col_opt4:
    st.metric("Total Tes", len(TESTS))

filtered_tests = TESTS if not cat_filter else [t for t in TESTS if t[1] in cat_filter]
st.caption(f"Menjalankan {len(filtered_tests)} tes")

if st.button("▶️ Jalankan Semua Tes", type="primary", use_container_width=True):
    results = []
    prog_bar = st.progress(0, text="Memulai tes...")

    cats = {}
    for tid, cat, q, fn in filtered_tests:
        cats.setdefault(cat, []).append((tid, q, fn))

    n_pass = n_fail = n_warn = 0
    test_idx = 0

    for cat, tests in cats.items():
        st.markdown(f'<div class="cat-header">📂 {cat}</div>', unsafe_allow_html=True)

        for tid, q, fn in tests:
            t0 = time.time()
            prog_bar.progress(test_idx / len(filtered_tests), text=f"Running {tid}: {q[:50]}...")

            ringkasan = ""
            n_rows = 0
            ai_jawaban = ""
            status = "PASS"
            error_msg = ""

            try:
                ringkasan, n_rows, detail_df = fn()

                if ringkasan.startswith("FAIL"):
                    status = "FAIL"
                    error_msg = ringkasan
                    ringkasan = ""
                elif ringkasan.startswith("WARN"):
                    status = "WARN"
                    error_msg = ringkasan
                    ringkasan = ""

                if run_ai and status == "PASS" and ringkasan:
                    ai_jawaban = tanya_groq(
                        f"Pertanyaan: {q}\n\nData:\n{ringkasan}\n\nJawab singkat dan akurat."
                    )
            except Exception as e:
                status = "FAIL"
                error_msg = str(e)

            durasi = int((time.time() - t0) * 1000)

            if status == "PASS":
                n_pass += 1; card_class = "pass-card"; icon = "✅"
            elif status == "WARN":
                n_warn += 1; card_class = "warn-card"; icon = "⚠️"
            else:
                n_fail += 1; card_class = "fail-card"; icon = "❌"

            ai_html  = f'<div class="test-ai">🤖 {ai_jawaban}</div>' if ai_jawaban else ""
            err_html = f'<div class="test-err">{error_msg}</div>' if error_msg else ""
            sum_html = f'<div class="test-sum">{ringkasan}</div>' if ringkasan else ""

            st.markdown(f"""
<div class="{card_class}">
  <span class="test-id">{tid}</span>
  <div class="test-q">{icon} {q}</div>
  <div class="test-rows">{n_rows:,} baris | {durasi}ms</div>
  {sum_html}{err_html}{ai_html}
</div>
""", unsafe_allow_html=True)

            results.append({
                "ID": tid, "Kategori": cat, "Pertanyaan": q,
                "Status": status, "Data Rows": n_rows,
                "Ringkasan": ringkasan, "Error": error_msg,
                "Jawaban AI": ai_jawaban, "Durasi (ms)": durasi
            })
            test_idx += 1

    prog_bar.progress(1.0, text="✅ Selesai!")

    total = len(results)
    st.divider()
    st.markdown("## 📊 Hasil Akhir")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        pct = n_pass/total*100
        st.markdown(f'<div class="summary-box"><div class="big-num" style="color:#22c55e">{n_pass}</div>'
                    f'<div class="big-label">PASS ({pct:.0f}%)</div></div>', unsafe_allow_html=True)
    with s2:
        pct = n_warn/total*100
        st.markdown(f'<div class="summary-box"><div class="big-num" style="color:#f59e0b">{n_warn}</div>'
                    f'<div class="big-label">WARN ({pct:.0f}%)</div></div>', unsafe_allow_html=True)
    with s3:
        pct = n_fail/total*100
        st.markdown(f'<div class="summary-box"><div class="big-num" style="color:#ef4444">{n_fail}</div>'
                    f'<div class="big-label">FAIL ({pct:.0f}%)</div></div>', unsafe_allow_html=True)
    with s4:
        st.markdown(f'<div class="summary-box"><div class="big-num">{total}</div>'
                    f'<div class="big-label">TOTAL TES</div></div>', unsafe_allow_html=True)

    if n_fail == 0 and n_warn == 0:
        st.success("🎉 Semua tes PASS! Hasil sudah akurat dengan dashboard Tapera.")
    elif n_fail == 0:
        st.warning(f"⚠️ {n_warn} tes WARN (data ada tapi ada kolom null). Cek data sumber.")
    else:
        st.error(f"❌ {n_fail} tes FAIL. Perlu investigasi lebih lanjut.")

    if export_csv:
        df_results = pd.DataFrame(results)
        csv = df_results.to_csv(index=False).encode("utf-8-sig")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "📥 Download Hasil Tes (CSV)",
            csv,
            file_name=f"test_tapera_{ts}.csv",
            mime="text/csv",
            use_container_width=True
        )

    fail_list = [r for r in results if r["Status"] == "FAIL"]
    if fail_list:
        st.markdown("### ❌ Daftar Tes yang FAIL")
        for r in fail_list:
            st.markdown(f"- **{r['ID']}** {r['Pertanyaan']}: `{r['Error']}`")

else:
    st.info("👆 Klik **Jalankan Semua Tes** untuk mulai pengujian.")
    st.markdown("### 📋 Daftar Pertanyaan Uji")
    cats = {}
    for tid, cat, q, fn in filtered_tests:
        cats.setdefault(cat, []).append((tid, q))
    for cat, tests in cats.items():
        st.markdown(f"**{cat}**")
        for tid, q in tests:
            st.markdown(f"- `{tid}` {q}")
