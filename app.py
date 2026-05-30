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
GROQ_KEY = st.secrets.get("GROQ_KEY", "")
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

def parse_rupiah(val) -> float:
    """
    Parse angka format Indonesia ke float.
    Contoh: '156.500.000' -> 156500000.0
             '5%' -> 5.0
             '5.252.280' -> 5252280.0
    """
    if val is None:
        return float('nan')
    s = str(val).strip()
    if not s or s in ('', 'None', 'null', '-'):
        return float('nan')
    # Hapus karakter non-numerik kecuali titik, koma, minus
    s = s.replace('Rp', '').replace(' ', '').replace('%', '').strip()
    # Hitung titik dan koma
    dots = s.count('.')
    commas = s.count(',')
    if dots > 1:
        # Titik = pemisah ribuan (format Indonesia): 156.500.000
        s = s.replace('.', '')
        if commas == 1:
            s = s.replace(',', '.')
    elif dots == 1 and commas == 1:
        # Mungkin: 1.500,50 -> 1500.50
        s = s.replace('.', '').replace(',', '.')
    elif dots == 0 and commas == 1:
        # Mungkin desimal: 5,5 -> 5.5
        s = s.replace(',', '.')
    # dots==1 dan commas==0: biarkan (sudah standar: 156.5)
    try:
        return float(s)
    except (ValueError, TypeError):
        return float('nan')


def count_total() -> int:
    """Hitung total baris via content-range header Supabase."""
    try:
        h = sb_headers()
        h["Prefer"] = "count=exact"
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h,
            params={"select": "id", "limit": "1"},
            timeout=15
        )
        r.raise_for_status()
        # content-range format: "0-0/997000" -> ambil angka setelah /
        ct = r.headers.get("content-range", "")
        if "/" in ct:
            total = ct.split("/")[-1].strip()
            if total != "*" and total.isdigit():
                return int(total)
        # Fallback: coba header X-Total-Count
        xtotal = r.headers.get("X-Total-Count", "0")
        return int(xtotal) if xtotal.isdigit() else 0
    except Exception as e:
        return 0

def fetch_agg(group_col: str, filter_col: str = None,
              filter_val: str = None, top_n: int = 30) -> pd.DataFrame:
    """COUNT(*) GROUP BY dengan pagination sampai 200k baris."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    params = {"select": group_col}
    if filter_col and filter_val:
        params[filter_col] = f"eq.{filter_val}"

    all_data = []
    offset = 0
    batch = 1000
    while True:
        p = {**params, "limit": str(batch), "offset": str(offset)}
        try:
            r = requests.get(url, headers=h, params=p, timeout=30)
            r.raise_for_status()
            chunk = r.json()
            if not chunk: break
            all_data.extend(chunk)
            if len(chunk) < batch: break
            offset += batch
            if offset >= 1000000: break
        except:
            break

    if not all_data:
        return pd.DataFrame()
    df = pd.DataFrame(all_data)
    if group_col not in df.columns:
        return pd.DataFrame()
    result = df[group_col].value_counts().nlargest(top_n).reset_index()
    result.columns = [group_col, "jumlah"]
    return result

def fetch_numeric_stats(col: str, group_col: str = None,
                        filter_col: str = None, filter_val: str = None,
                        limit: int = 50000) -> pd.DataFrame:
    """Ambil kolom numerik + opsional group_col — pakai pagination penuh."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    select = f"{col},{group_col}" if group_col else col
    params_base = {"select": select}
    if filter_col and filter_val:
        params_base[filter_col] = f"eq.{filter_val}"
    
    all_data = []
    offset = 0
    batch = 1000
    while True:
        p = {**params_base, "limit": str(batch), "offset": str(offset)}
        try:
            r = requests.get(url, headers=h, params=p, timeout=30)
            r.raise_for_status()
            chunk = r.json()
            if not chunk: break
            all_data.extend(chunk)
            if len(chunk) < batch: break
            offset += batch
            if offset >= 1000000: break
        except: break
    return pd.DataFrame(all_data) if all_data else pd.DataFrame()

def fetch_multi_group(col1: str, col2: str, limit: int = 100000) -> pd.DataFrame:
    """Ambil 2 kolom untuk groupby kombinasi — pagination penuh."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    params_base = {"select": f"{col1},{col2}"}
    all_data = []
    offset = 0
    batch = 1000
    while True:
        p = {**params_base, "limit": str(batch), "offset": str(offset)}
        try:
            r = requests.get(url, headers=h, params=p, timeout=30)
            r.raise_for_status()
            chunk = r.json()
            if not chunk: break
            all_data.extend(chunk)
            if len(chunk) < batch: break
            offset += batch
            if offset >= 1000000: break
        except: break
    return pd.DataFrame(all_data) if all_data else pd.DataFrame()

def fetch_tren(filter_col: str = None, filter_val: str = None) -> pd.DataFrame:
    """Tren per tahun_realisasi — pagination penuh, TANPA limit di params base."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    # KRITIS: jangan taruh limit di params_base! limit harus di dalam loop per-batch
    params_base = {"select": "tahun_realisasi"}
    if filter_col and filter_val:
        params_base[filter_col] = f"eq.{filter_val}"
    all_data = []
    offset = 0
    batch = 1000
    while True:
        p = {**params_base, "limit": str(batch), "offset": str(offset)}
        try:
            r = requests.get(url, headers=h, params=p, timeout=30)
            r.raise_for_status()
            chunk = r.json()
            if not chunk: break
            all_data.extend(chunk)
            if len(chunk) < batch: break
            offset += batch
            if offset >= 1200000: break
        except:
            break
    if not all_data:
        return pd.DataFrame()
    df = pd.DataFrame(all_data)
    result = df["tahun_realisasi"].value_counts().sort_index().reset_index()
    result.columns = ["Tahun", "Unit"]
    return result

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
# TEST DEFINITIONS
# Setiap test: {id, kategori, pertanyaan, fn}
# fn() -> (ringkasan_str, n_rows, detail_df_or_None)
# ============================================================
def run_A1():
    n = count_total()
    return f"Total: {n:,} unit", n, None

def run_A1b():
    """Fallback count: hitung via pagination manual kalau count_total = 0."""
    n = count_total()
    if n > 0:
        return f"✅ count_total OK: {n:,} unit", n, None
    # Fallback: tarik id saja dan hitung
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    total = 0
    offset = 0
    batch = 1000
    while True:
        p = {"select": "id", "limit": str(batch), "offset": str(offset)}
        try:
            r = requests.get(url, headers=h, params=p, timeout=30)
            r.raise_for_status()
            chunk = r.json()
            total += len(chunk)
            if len(chunk) < batch: break
            offset += batch
            if offset >= 1200000: break
        except: break
    return f"⚠️ count_total=0 (bug Prefer header), fallback pagination: {total:,} unit", total, None

def run_A8():
    """Debug: tampilkan nama kolom asli dan sample nilai dari Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    try:
        r = requests.get(url, headers=h, params={"limit": "3"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            return "FAIL: tidak ada data sama sekali", 0, None
        cols = list(data[0].keys())
        # Tampilkan semua kolom dan nilai baris pertama
        sample_lines = []
        for k, v in data[0].items():
            sample_lines.append(f"  {k}: {repr(v)}")
        return f"Semua kolom ({len(cols)}):\n{chr(10).join(sample_lines)}", len(data), None
    except Exception as e:
        return f"FAIL: {e}", 0, None

def run_A2():
    df = fetch_numeric_stats("nilai_flpp", limit=1000000)
    if df.empty or "nilai_flpp" not in df.columns:
        return "FAIL: kolom nilai_flpp tidak ada", 0, None
    df["nilai_flpp"] = df["nilai_flpp"].apply(parse_rupiah)
    total = df["nilai_flpp"].sum()
    avg   = df["nilai_flpp"].mean()
    return f"Total: Rp {total/1e12:.2f} T\nRata-rata per unit: Rp {avg:,.0f}", len(df), None

def run_A3():
    df = fetch_tren()
    if df.empty:
        return "FAIL: tidak ada data tahun", 0, None
    tahun_list = sorted(df["Tahun"].dropna().unique().tolist())
    return f"Rentang tahun: {tahun_list[0]}–{tahun_list[-1]}\nTahun tersedia: {', '.join(str(t) for t in tahun_list)}", len(df), df

def run_A4():
    df = fetch_agg("bank", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data bank", 0, None
    banks = df["bank"].tolist()
    return f"{len(banks)} bank: {', '.join(banks[:5])}{'...' if len(banks)>5 else ''}", len(df), df

def run_A5():
    df = fetch_agg("provinsi", top_n=50)
    if df.empty:
        return "FAIL: tidak ada data provinsi", 0, None
    return f"{len(df)} provinsi terdeteksi\nContoh: {', '.join(df['provinsi'].tolist()[:5])}", len(df), df

def run_A6():
    df = fetch_numeric_stats("harga_rumah", limit=50000)
    if df.empty or "harga_rumah" not in df.columns:
        return "FAIL: kolom harga_rumah kosong", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    df = df.dropna(subset=["harga_rumah"])
    vmin = df["harga_rumah"].min()
    vmax = df["harga_rumah"].max()
    vavg = df["harga_rumah"].mean()
    if pd.isna(vmin):
        return "FAIL: semua nilai harga_rumah null", len(df), None
    return f"Min: Rp {vmin:,.0f}\nMax: Rp {vmax:,.0f}\nRata-rata: Rp {vavg:,.0f}", len(df), None

def run_A7():
    df = fetch_agg("jenis_rumah", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data jenis_rumah", 0, None
    return "\n".join(f"  {i+1}. {r['jenis_rumah']}: {r['jumlah']:,}" for i,r in df.iterrows()), len(df), df

def run_B1():
    df = fetch_agg("provinsi", top_n=38)
    if df.empty:
        return "FAIL", 0, None
    top5 = "\n".join(f"  {i+1}. {r['provinsi']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 provinsi:\n{top5}", len(df), df

def run_B2():
    df = fetch_agg("kabupaten", top_n=20)
    if df.empty:
        return "FAIL", 0, None
    top10 = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 kabupaten:\n{top10}", len(df), df

def run_B3():
    df = fetch_agg("nama_pengembang", top_n=20)
    if df.empty:
        return "FAIL", 0, None
    top10 = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 pengembang:\n{top10}", len(df), df

def run_B4():
    df = fetch_agg("nama_perumahan", top_n=20)
    if df.empty:
        return "FAIL", 0, None
    top10 = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 perumahan:\n{top10}", len(df), df

def run_B5():
    df = fetch_agg("bank", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    top5 = "\n".join(f"  {i+1}. {r['bank']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 bank:\n{top5}", len(df), df

def run_B6():
    df = fetch_agg("nama_perumahan", "tahun_realisasi", "2023", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data 2023", 0, None
    top10 = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 perumahan terbanyak 2023:\n{top10}", len(df), df

def run_B7():
    df = fetch_agg("nama_pengembang", "provinsi", "JAWA BARAT", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data Jawa Barat", 0, None
    top5 = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 pengembang Jawa Barat:\n{top5}", len(df), df

def run_B8():
    df = fetch_agg("asosiasi", top_n=10)
    if df.empty:
        return "FAIL", 0, None
    top5 = "\n".join(f"  {i+1}. {r['asosiasi']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 asosiasi:\n{top5}", len(df), df

def run_B9():
    df = fetch_agg("kabupaten", "provinsi", "JAWA TIMUR", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data Jawa Timur", 0, None
    top10 = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 kabupaten Jawa Timur:\n{top10}", len(df), df

def run_B10():
    df = fetch_agg("nama_pengembang", "tahun_realisasi", "2024", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data 2024", 0, None
    top5 = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 pengembang 2024:\n{top5}", len(df), df

def run_C1():
    df = fetch_agg("provinsi", top_n=50)
    if df.empty or "JAWA BARAT" not in df["provinsi"].values:
        return "FAIL: Jawa Barat tidak ditemukan", 0, None
    n = df[df["provinsi"] == "JAWA BARAT"]["jumlah"].values[0]
    total = df["jumlah"].sum()
    pct = n / total * 100
    return f"Jawa Barat: {n:,} unit ({pct:.1f}% dari total {total:,})", n, None

def run_C2():
    df_tren = fetch_tren()
    if df_tren.empty:
        return "FAIL: tidak ada data tahun", 0, None
    r2023 = df_tren[df_tren["Tahun"] == 2023]
    n = int(r2023["Unit"].values[0]) if not r2023.empty else 0
    return f"Unit FLPP tahun 2023: {n:,}", n, df_tren

def run_C3():
    df = fetch_agg("bank", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data bank", 0, None
    btn_row = df[df["bank"].str.contains("BTN", case=False, na=False)]
    if btn_row.empty:
        return "BTN tidak ditemukan, nama bank tersedia:\n" + \
               "\n".join(f"  - {b}" for b in df["bank"].head(8).tolist()), 0, df
    n = btn_row["jumlah"].sum()
    total = df["jumlah"].sum()
    return f"BTN: {n:,} unit ({n/total*100:.1f}% dari total)", n, None

def run_C4():
    df = fetch_agg("nama_perumahan", "provinsi", "SUMATERA UTARA", top_n=30)
    if df.empty:
        return "FAIL: tidak ada data Sumatera Utara", 0, None
    top10 = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 perumahan di Sumatera Utara:\n{top10}", len(df), df

def run_C5():
    df = fetch_agg("nama_pengembang", "provinsi", "KALIMANTAN TIMUR", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data Kalimantan Timur", 0, None
    top5 = "\n".join(f"  {i+1}. {r['nama_pengembang']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 pengembang Kalimantan Timur:\n{top5}", len(df), df

def run_C6():
    df = fetch_agg("kabupaten", "provinsi", "BANTEN", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data Banten", 0, None
    s = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i,r in df.iterrows())
    return f"Distribusi Banten:\n{s}", len(df), df

def run_C7():
    df = fetch_agg("nama_perumahan", "bank", "BANK BTN", top_n=20)
    if df.empty:
        # coba nama lain
        df = fetch_agg("nama_perumahan", "bank", "BTN", top_n=20)
    if df.empty:
        return "FAIL: data perumahan BTN tidak ditemukan", 0, None
    top10 = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 perumahan dibiayai BTN:\n{top10}", len(df), df

def run_C8():
    df = fetch_agg("provinsi", "tahun_realisasi", "2022", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data 2022", 0, None
    top5 = "\n".join(f"  {i+1}. {r['provinsi']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 provinsi tahun 2022:\n{top5}", len(df), df

def run_C9():
    df = fetch_agg("kabupaten", "tahun_realisasi", "2024", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data 2024", 0, None
    top10 = "\n".join(f"  {i+1}. {r['kabupaten']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 kabupaten 2024:\n{top10}", len(df), df

def run_C10():
    df = fetch_agg("nama_perumahan", "provinsi", "SULAWESI SELATAN", top_n=20)
    if df.empty:
        return "FAIL: tidak ada data Sulawesi Selatan", 0, None
    top10 = "\n".join(f"  {i+1}. {r['nama_perumahan']}: {r['jumlah']:,}" for i,r in df.head(10).iterrows())
    return f"Top 10 perumahan di Sulawesi Selatan:\n{top10}", len(df), df

def run_D1():
    df = fetch_tren()
    if df.empty:
        return "FAIL: tidak ada data tren", 0, None
    s = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _,r in df.iterrows())
    return f"Tren per tahun:\n{s}", len(df), df

def run_D2():
    df = fetch_tren()
    if df.empty:
        return "FAIL", 0, None
    best = df.loc[df["Unit"].idxmax()]
    return f"Tahun terbanyak: {int(best['Tahun'])} dengan {int(best['Unit']):,} unit", len(df), df

def run_D3():
    df = fetch_tren()
    if df.empty or len(df) < 2:
        return "FAIL: data tren kurang", 0, None
    df = df.sort_values("Tahun")
    results = []
    for i in range(1, len(df)):
        prev = df.iloc[i-1]
        curr = df.iloc[i]
        delta = curr["Unit"] - prev["Unit"]
        pct = delta / prev["Unit"] * 100
        trend = "📈" if delta > 0 else "📉"
        results.append(f"  {trend} {int(prev['Tahun'])}→{int(curr['Tahun'])}: {delta:+,} ({pct:+.1f}%)")
    return "Perubahan YoY:\n" + "\n".join(results), len(df), df

def run_D4():
    df_tren = fetch_tren()
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
    df = fetch_tren("provinsi", "JAWA BARAT")
    if df.empty:
        return "FAIL: tidak ada data Jawa Barat per tahun", 0, None
    s = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _,r in df.iterrows())
    return f"Tren Jawa Barat per tahun:\n{s}", len(df), df

def run_D6():
    df = fetch_tren("bank", "BANK BTN")
    if df.empty:
        # coba nama singkat
        df = fetch_tren("bank", "BTN")
    if df.empty:
        return "WARN: data BTN per tahun tidak ditemukan", 0, None
    s = "\n".join(f"  {r['Tahun']}: {r['Unit']:,}" for _,r in df.iterrows())
    return f"Tren BTN per tahun:\n{s}", len(df), df

def run_E1():
    df = fetch_agg("kelamin", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data kelamin", 0, None
    total = df["jumlah"].sum()
    s = "\n".join(f"  {r['kelamin']}: {r['jumlah']:,} ({r['jumlah']/total*100:.1f}%)" for _,r in df.iterrows())
    return f"Distribusi gender:\n{s}", len(df), df

def run_E2():
    df = fetch_agg("pekerjaan", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data pekerjaan", 0, None
    top5 = "\n".join(f"  {i+1}. {r['pekerjaan']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 pekerjaan pembeli:\n{top5}", len(df), df

def run_E3():
    df = fetch_numeric_stats("penghasilan", limit=50000)
    if df.empty or "penghasilan" not in df.columns:
        return "FAIL: kolom penghasilan tidak ada", 0, None
    df["penghasilan"] = df["penghasilan"].apply(parse_rupiah)
    if df["penghasilan"].isna().all():
        return "WARN: semua nilai penghasilan null", len(df), None
    avg = df["penghasilan"].mean()
    med = df["penghasilan"].median()
    return f"Rata-rata: Rp {avg:,.0f}\nMedian: Rp {med:,.0f}", len(df), None

def run_E4():
    df = fetch_agg("tenor", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data tenor", 0, None
    total = df["jumlah"].sum()
    s = "\n".join(f"  {r['tenor']} bln ({r['tenor']//12} thn): {r['jumlah']:,} ({r['jumlah']/total*100:.1f}%)" for _,r in df.iterrows())
    return f"Distribusi tenor:\n{s}", len(df), df

def run_E5():
    df = fetch_numeric_stats("harga_rumah", limit=50000)
    if df.empty or "harga_rumah" not in df.columns:
        return "FAIL: kolom harga_rumah tidak ada", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    if df["harga_rumah"].isna().all():
        return "WARN: semua nilai harga_rumah null", len(df), None
    avg = df["harga_rumah"].mean()
    return f"Rata-rata harga rumah: Rp {avg:,.0f}", len(df), None

def run_E6():
    df = fetch_agg("kelamin", "tahun_realisasi", "2023", top_n=5)
    if df.empty:
        return "FAIL: tidak ada data gender 2023", 0, None
    total = df["jumlah"].sum()
    s = "\n".join(f"  {r['kelamin']}: {r['jumlah']:,} ({r['jumlah']/total*100:.1f}%)" for _,r in df.iterrows())
    return f"Gender pembeli 2023:\n{s}", len(df), df

def run_E7():
    df = fetch_agg("pekerjaan", "provinsi", "DKI JAKARTA", top_n=10)
    if df.empty:
        return "WARN: DKI Jakarta mungkin nama berbeda atau tidak ada data", 0, None
    top5 = "\n".join(f"  {i+1}. {r['pekerjaan']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 pekerjaan di DKI Jakarta:\n{top5}", len(df), df

def debug_kolom_numerik() -> str:
    """Ambil 3 baris data untuk cek nama kolom & sample nilai aktual."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    try:
        r = requests.get(url, headers=h, params={"limit": "3"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            return "Tidak ada data"
        cols = list(data[0].keys())
        # Cari kolom yang kemungkinan numerik
        num_cols = [c for c in cols if any(k in c.lower() for k in
                    ["harga","nilai","flpp","bunga","penghasilan","suku","kredit","uang"])]
        sample = data[0]
        sample_str = "\n".join(f"  {k}: {v}" for k,v in sample.items() if k in num_cols)
        return f"Kolom numerik ditemukan: {num_cols}\nSample baris 1:\n{sample_str}\nSemua kolom: {cols}"
    except Exception as e:
        return f"Error debug: {e}"

def run_F1():
    df = fetch_numeric_stats("harga_rumah", limit=50000)
    if df.empty:
        return "FAIL", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    if df["harga_rumah"].isna().all():
        debug = debug_kolom_numerik()
        return f"WARN: harga_rumah semua null\nDEBUG: {debug}", len(df), None
    return f"Min: Rp {df['harga_rumah'].min():,.0f}\nMax: Rp {df['harga_rumah'].max():,.0f}\nRata-rata: Rp {df['harga_rumah'].mean():,.0f}", len(df), None

def run_F2():
    df = fetch_numeric_stats("nilai_flpp", limit=100000)
    if df.empty:
        return "FAIL", 0, None
    df["nilai_flpp"] = df["nilai_flpp"].apply(parse_rupiah)
    if df["nilai_flpp"].isna().all():
        debug = debug_kolom_numerik()
        return f"WARN: nilai_flpp semua null\nDEBUG: {debug}", len(df), None
    avg = df["nilai_flpp"].mean()
    total = df["nilai_flpp"].sum()
    return f"Rata-rata per unit: Rp {avg:,.0f}\nTotal ({len(df):,} sample): Rp {total/1e12:.2f}T", len(df), None

def run_F3():
    df = fetch_numeric_stats("harga_rumah", "provinsi", limit=50000)
    if df.empty:
        return "FAIL", 0, None
    df["harga_rumah"] = df["harga_rumah"].apply(parse_rupiah)
    if df["harga_rumah"].isna().all():
        return "WARN: harga_rumah semua null\n(Kolom mungkin bernama berbeda di Supabase)", len(df), None
    avg_prov = df.groupby("provinsi")["harga_rumah"].mean().nlargest(5).reset_index()
    s = "\n".join(f"  {i+1}. {r['provinsi']}: Rp {r['harga_rumah']:,.0f}" for i,r in avg_prov.iterrows())
    return f"Top 5 provinsi harga tertinggi:\n{s}", len(df), avg_prov

def run_F4():
    df = fetch_numeric_stats("nilai_flpp", "bank", limit=100000)
    if df.empty:
        return "FAIL", 0, None
    df["nilai_flpp"] = df["nilai_flpp"].apply(parse_rupiah)
    if df["nilai_flpp"].isna().all():
        return "WARN: nilai_flpp semua null\n(Kolom mungkin bernama berbeda di Supabase)", len(df), None
    by_bank = df.groupby("bank")["nilai_flpp"].sum().nlargest(5).reset_index()
    s = "\n".join(f"  {i+1}. {r['bank']}: Rp {r['nilai_flpp']/1e12:.2f}T" for i,r in by_bank.iterrows())
    return f"Nilai kredit per bank (top 5):\n{s}", len(df), by_bank

def run_F5():
    df = fetch_numeric_stats("suku_bunga_kpr", limit=50000)
    if df.empty:
        return "FAIL", 0, None
    df["suku_bunga_kpr"] = df["suku_bunga_kpr"].apply(parse_rupiah)
    if df["suku_bunga_kpr"].isna().all():
        debug = debug_kolom_numerik()
        return f"WARN: suku_bunga_kpr semua null\nDEBUG: {debug}", len(df), None
    avg = df["suku_bunga_kpr"].mean()
    vmin = df["suku_bunga_kpr"].min()
    vmax = df["suku_bunga_kpr"].max()
    return f"Suku bunga KPR:\nMin: {vmin:.2f}%\nMax: {vmax:.2f}%\nRata-rata: {avg:.2f}%", len(df), None

def run_G1():
    df = fetch_multi_group("provinsi", "bank", limit=100000)
    if df.empty:
        return "FAIL", 0, None
    dom = df.groupby(["provinsi","bank"]).size().reset_index(name="n")
    dom_idx = dom.groupby("provinsi")["n"].idxmax()
    result = dom.loc[dom_idx, ["provinsi","bank","n"]].sort_values("n", ascending=False)
    s = "\n".join(f"  {r['provinsi']}: {r['bank']} ({r['n']:,})" for _,r in result.head(10).iterrows())
    return f"Bank dominan per provinsi (top 10):\n{s}", len(df), result

def run_G2():
    df = fetch_multi_group("provinsi", "nama_pengembang", limit=1000000)
    if df.empty:
        return "FAIL", 0, None
    dev_per_prov = df.groupby("provinsi")["nama_pengembang"].nunique().reset_index()
    dev_per_prov.columns = ["Provinsi", "Jumlah Pengembang"]
    dev_per_prov = dev_per_prov.sort_values("Jumlah Pengembang", ascending=False)
    s = "\n".join(f"  {r['Provinsi']}: {r['Jumlah Pengembang']:,} pengembang" for _,r in dev_per_prov.head(10).iterrows())
    return f"Jumlah pengembang per provinsi (top 10):\n{s}", len(df), dev_per_prov

def run_G3():
    df = fetch_multi_group("tahun_realisasi", "provinsi", limit=1000000)
    if df.empty:
        return "FAIL", 0, None
    jabar = df[df["provinsi"] == "JAWA BARAT"]
    luar_jabar = df[df["provinsi"] != "JAWA BARAT"]
    by_tahun_jabar = jabar.groupby("tahun_realisasi").size().reset_index(name="JAWA BARAT")
    by_tahun_luar  = luar_jabar.groupby("tahun_realisasi").size().reset_index(name="Luar Jabar")
    merged = by_tahun_jabar.merge(by_tahun_luar, on="tahun_realisasi", how="outer").fillna(0)
    merged = merged.sort_values("tahun_realisasi")
    s = "\n".join(f"  {int(r['tahun_realisasi'])}: Jabar={int(r['JAWA BARAT']):,} | Luar={int(r['Luar Jabar']):,}"
                  for _,r in merged.iterrows())
    return f"Jawa Barat vs Luar Jawa Barat per tahun:\n{s}", len(df), merged

def run_G4():
    df_j = fetch_agg("provinsi", top_n=50)
    if df_j.empty:
        return "FAIL", 0, None
    pulau_jawa = ["JAWA BARAT","JAWA TENGAH","JAWA TIMUR","DKI JAKARTA","BANTEN","DI YOGYAKARTA","DAERAH ISTIMEWA YOGYAKARTA"]
    jawa = df_j[df_j["provinsi"].isin(pulau_jawa)]["jumlah"].sum()
    total = df_j["jumlah"].sum()
    luar = total - jawa
    return (f"Jawa: {jawa:,} unit ({jawa/total*100:.1f}%)\n"
            f"Luar Jawa: {luar:,} unit ({luar/total*100:.1f}%)\n"
            f"Total: {total:,}"), total, None

def run_G5():
    df_bank = fetch_agg("bank", top_n=10)
    df_dev  = fetch_agg("nama_pengembang", top_n=10)
    df_prov = fetch_agg("provinsi", top_n=10)
    if df_bank.empty or df_dev.empty or df_prov.empty:
        return "FAIL", 0, None
    
    n_bank = df_bank["jumlah"].sum()
    top_bank = df_bank.iloc[0]
    top_dev  = df_dev.iloc[0]
    top_prov = df_prov.iloc[0]
    
    return (f"Ringkasan dominasi:\n"
            f"  🏦 Bank terbesar: {top_bank['bank']} ({top_bank['jumlah']:,} unit)\n"
            f"  🏗️ Pengembang terbesar: {top_dev['nama_pengembang']} ({top_dev['jumlah']:,} unit)\n"
            f"  🗺️ Provinsi terbesar: {top_prov['provinsi']} ({top_prov['jumlah']:,} unit)"), 0, None

def run_G6():
    df = fetch_agg("asosiasi", "tahun_realisasi", "2023", top_n=10)
    if df.empty:
        return "FAIL: tidak ada data asosiasi 2023", 0, None
    s = "\n".join(f"  {i+1}. {r['asosiasi']}: {r['jumlah']:,}" for i,r in df.head(5).iterrows())
    return f"Top 5 asosiasi tahun 2023:\n{s}", len(df), df

def run_G7():
    df_prov = fetch_agg("provinsi", top_n=50)
    if df_prov.empty:
        return "FAIL", 0, None
    all_prov = ["ACEH","SUMATERA UTARA","SUMATERA BARAT","RIAU","JAMBI",
                "SUMATERA SELATAN","BENGKULU","LAMPUNG","KEPULAUAN BANGKA BELITUNG",
                "KEPULAUAN RIAU","DKI JAKARTA","JAWA BARAT","JAWA TENGAH",
                "DI YOGYAKARTA","DAERAH ISTIMEWA YOGYAKARTA","JAWA TIMUR","BANTEN",
                "BALI","NUSA TENGGARA BARAT","NUSA TENGGARA TIMUR","KALIMANTAN BARAT",
                "KALIMANTAN TENGAH","KALIMANTAN SELATAN","KALIMANTAN TIMUR",
                "KALIMANTAN UTARA","SULAWESI UTARA","SULAWESI TENGAH","SULAWESI SELATAN",
                "SULAWESI TENGGARA","GORONTALO","SULAWESI BARAT","MALUKU","MALUKU UTARA",
                "PAPUA BARAT","PAPUA"]
    found = set(df_prov["provinsi"].str.upper().tolist())
    missing = [p for p in all_prov if p not in found and p.replace("DI ","DAERAH ISTIMEWA ") not in found]
    return (f"Provinsi dengan data ({len(found)}): {', '.join(sorted(found)[:10])}...\n"
            f"Mungkin tidak ada data ({len(missing)}): {', '.join(missing[:5])}{'...' if len(missing)>5 else ''}"), len(df_prov), df_prov

def run_G8():
    df_j = fetch_agg("jenis_rumah", top_n=10)
    df_bank = fetch_agg("bank", top_n=5)
    if df_j.empty or df_bank.empty:
        return "FAIL", 0, None
    jenis_list = "\n".join(f"  {r['jenis_rumah']}: {r['jumlah']:,}" for _,r in df_j.iterrows())
    bank_list  = "\n".join(f"  {r['bank']}: {r['jumlah']:,}" for _,r in df_bank.iterrows())
    return f"Jenis rumah:\n{jenis_list}\n\nTop bank:\n{bank_list}", 0, None

# ============================================================
# TEST REGISTRY
# ============================================================
TESTS = [
    # A — ANGKA DASAR
    ("A1","A. Angka Dasar","Berapa total unit FLPP yang sudah terealisasi?", run_A1),
    ("A1b","A. Angka Dasar","[Debug] Count fallback via pagination (jika A1=0)", run_A1b),
    ("A8","A. Angka Dasar","[Debug] Nama kolom asli & sample nilai dari Supabase", run_A8),
    ("A2","A. Angka Dasar","Berapa total nilai kredit FLPP (Rp) dan rata-rata per unit?", run_A2),
    ("A3","A. Angka Dasar","Data tersedia dari tahun berapa sampai tahun berapa?", run_A3),
    ("A4","A. Angka Dasar","Ada berapa bank pelaksana FLPP dalam data ini?", run_A4),
    ("A5","A. Angka Dasar","Berapa jumlah provinsi yang tercatat?", run_A5),
    ("A6","A. Angka Dasar","Berapa kisaran harga rumah FLPP (min, max, rata-rata)?", run_A6),
    ("A7","A. Angka Dasar","Ada jenis rumah apa saja dalam data FLPP?", run_A7),

    # B — RANKING & TOP-N
    ("B1","B. Ranking & Top-N","Provinsi mana yang paling banyak unit FLPP (top 10)?", run_B1),
    ("B2","B. Ranking & Top-N","10 kabupaten/kota dengan realisasi FLPP terbanyak nasional?", run_B2),
    ("B3","B. Ranking & Top-N","Top 10 pengembang paling produktif secara nasional?", run_B3),
    ("B4","B. Ranking & Top-N","Top 10 perumahan dengan unit FLPP terealisasi terbanyak?", run_B4),
    ("B5","B. Ranking & Top-N","Bank mana yang paling aktif? Berapa market share-nya?", run_B5),
    ("B6","B. Ranking & Top-N","Top 10 perumahan terbanyak di tahun 2023?", run_B6),
    ("B7","B. Ranking & Top-N","Top 5 pengembang di Jawa Barat?", run_B7),
    ("B8","B. Ranking & Top-N","Asosiasi pengembang mana yang paling banyak unit FLPP?", run_B8),
    ("B9","B. Ranking & Top-N","Top 10 kabupaten di Jawa Timur?", run_B9),
    ("B10","B. Ranking & Top-N","Top 5 pengembang paling aktif tahun 2024?", run_B10),

    # C — FILTER SPESIFIK
    ("C1","C. Filter Spesifik","Berapa total unit FLPP di Jawa Barat? Berapa persen dari nasional?", run_C1),
    ("C2","C. Filter Spesifik","Berapa unit FLPP yang terealisasi di tahun 2023?", run_C2),
    ("C3","C. Filter Spesifik","Berapa unit FLPP yang dibiayai BTN? Apa nama bank BTN di data?", run_C3),
    ("C4","C. Filter Spesifik","Sebutkan top 10 perumahan di Sumatera Utara!", run_C4),
    ("C5","C. Filter Spesifik","Pengembang apa yang aktif di Kalimantan Timur?", run_C5),
    ("C6","C. Filter Spesifik","Distribusi unit FLPP per kabupaten di Banten?", run_C6),
    ("C7","C. Filter Spesifik","Top 10 perumahan yang dibiayai BTN?", run_C7),
    ("C8","C. Filter Spesifik","Top 5 provinsi realisasi FLPP tahun 2022?", run_C8),
    ("C9","C. Filter Spesifik","Top 10 kabupaten realisasi FLPP tahun 2024?", run_C9),
    ("C10","C. Filter Spesifik","Top 10 perumahan di Sulawesi Selatan?", run_C10),

    # D — TREN & WAKTU
    ("D1","D. Tren & Waktu","Tren realisasi FLPP per tahun dari awal sampai sekarang?", run_D1),
    ("D2","D. Tren & Waktu","Tahun berapa realisasi FLPP paling banyak?", run_D2),
    ("D3","D. Tren & Waktu","Apakah realisasi naik atau turun setiap tahun? (YoY)", run_D3),
    ("D4","D. Tren & Waktu","Perbandingan realisasi 2022 vs 2024 — naik atau turun?", run_D4),
    ("D5","D. Tren & Waktu","Tren realisasi di Jawa Barat per tahun?", run_D5),
    ("D6","D. Tren & Waktu","Berapa unit FLPP per tahun yang dibiayai BTN?", run_D6),

    # E — PROFIL PEMBELI
    ("E1","E. Profil Pembeli","Berapa persen pembeli laki-laki vs perempuan?", run_E1),
    ("E2","E. Profil Pembeli","Pekerjaan apa yang paling banyak membeli rumah FLPP?", run_E2),
    ("E3","E. Profil Pembeli","Berapa rata-rata dan median penghasilan pembeli?", run_E3),
    ("E4","E. Profil Pembeli","Tenor KPR berapa tahun yang paling banyak dipilih?", run_E4),
    ("E5","E. Profil Pembeli","Berapa rata-rata harga rumah yang dibeli?", run_E5),
    ("E6","E. Profil Pembeli","Rasio gender pembeli di tahun 2023?", run_E6),
    ("E7","E. Profil Pembeli","Pekerjaan pembeli FLPP di DKI Jakarta?", run_E7),

    # F — HARGA & NILAI KREDIT
    ("F1","F. Harga & Nilai","Kisaran harga rumah FLPP (min, max, rata-rata)?", run_F1),
    ("F2","F. Harga & Nilai","Berapa rata-rata nilai kredit FLPP per unit?", run_F2),
    ("F3","F. Harga & Nilai","Provinsi mana yang rata-rata harga rumahnya paling tinggi?", run_F3),
    ("F4","F. Harga & Nilai","Berapa total nilai kredit per bank?", run_F4),
    ("F5","F. Harga & Nilai","Berapa rata-rata suku bunga KPR FLPP?", run_F5),

    # G — KOMBINASI & ANALITIK
    ("G1","G. Kombinasi","Bank dominan di setiap provinsi?", run_G1),
    ("G2","G. Kombinasi","Provinsi mana yang paling banyak pengembangnya?", run_G2),
    ("G3","G. Kombinasi","Perbandingan tren Jawa Barat vs provinsi lain per tahun?", run_G3),
    ("G4","G. Kombinasi","Perbandingan realisasi FLPP Jawa vs Luar Jawa?", run_G4),
    ("G5","G. Kombinasi","Siapa pemegang posisi teratas: bank, pengembang, provinsi?", run_G5),
    ("G6","G. Kombinasi","Asosiasi pengembang paling aktif di tahun 2023?", run_G6),
    ("G7","G. Kombinasi","Provinsi mana saja yang tidak memiliki data FLPP?", run_G7),
    ("G8","G. Kombinasi","Jenis rumah FLPP apa saja dan bank apa yang membiayainya?", run_G8),
]

# ============================================================
# UI
# ============================================================
st.markdown("# 🧪 Test Suite — Asisten AI Data Tapera")
st.markdown(f"**{len(TESTS)} pertanyaan uji** | 7 kategori | Data dari Supabase (aggregasi penuh)")
st.divider()

# Opsi test
col_opt1, col_opt2, col_opt3, col_opt4 = st.columns(4)
with col_opt1:
    run_ai = st.checkbox("Jalankan AI Groq per tes", value=False,
                         help="Centang untuk dapat jawaban AI via Groq. Lebih lambat tapi lebih informatif.")
with col_opt2:
    cat_filter = st.multiselect("Filter kategori:",
                                ["A. Angka Dasar","B. Ranking & Top-N","C. Filter Spesifik",
                                 "D. Tren & Waktu","E. Profil Pembeli","F. Harga & Nilai","G. Kombinasi"],
                                default=[])
with col_opt3:
    export_csv = st.checkbox("Export hasil ke CSV", value=True)
with col_opt4:
    st.metric("Total Tes", len(TESTS))

filtered_tests = TESTS if not cat_filter else [t for t in TESTS if t[1] in cat_filter]
st.caption(f"Menjalankan {len(filtered_tests)} tes")

if st.button("▶️ Jalankan Semua Tes", type="primary", use_container_width=True):
    results = []
    
    # Progress
    prog_bar = st.progress(0, text="Memulai tes...")
    
    # Grouping by category
    cats = {}
    for tid, cat, q, fn in filtered_tests:
        cats.setdefault(cat, []).append((tid, q, fn))
    
    n_pass = n_fail = n_warn = 0
    test_idx = 0
    
    for cat, tests in cats.items():
        st.markdown(f'<div class="cat-header">📂 {cat}</div>', unsafe_allow_html=True)
        
        for tid, q, fn in tests:
            t0 = time.time()
            prog_bar.progress(test_idx / len(filtered_tests),
                              text=f"Running {tid}: {q[:50]}...")
            
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
                
                # Jalankan AI jika diminta dan status bukan FAIL
                if run_ai and status in ["PASS"] and ringkasan:
                    ai_jawaban = tanya_groq(
                        f"Pertanyaan: {q}\n\nData:\n{ringkasan}\n\nJawab singkat dan akurat."
                    )
                    
            except Exception as e:
                status = "FAIL"
                error_msg = str(e)
            
            durasi = int((time.time() - t0) * 1000)
            
            # Status counter
            if status == "PASS":
                n_pass += 1
                card_class = "pass-card"
                icon = "✅"
            elif status == "WARN":
                n_warn += 1
                card_class = "warn-card"
                icon = "⚠️"
            else:
                n_fail += 1
                card_class = "fail-card"
                icon = "❌"
            
            # Render card
            ai_html = f'<div class="test-ai">🤖 {ai_jawaban}</div>' if ai_jawaban else ""
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
    
    # Summary
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
        st.success("🎉 Semua tes PASS! AI siap digunakan secara penuh.")
    elif n_fail == 0:
        st.warning(f"⚠️ {n_warn} tes WARN (data ada tapi ada kolom null). Cek data sumber.")
    else:
        st.error(f"❌ {n_fail} tes FAIL. Perlu investigasi lebih lanjut.")
    
    # Export CSV
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
    
    # Detail FAIL
    fail_list = [r for r in results if r["Status"] == "FAIL"]
    if fail_list:
        st.markdown("### ❌ Daftar Tes yang FAIL")
        for r in fail_list:
            st.markdown(f"- **{r['ID']}** {r['Pertanyaan']}: `{r['Error']}`")

else:
    # Preview
    st.info("👆 Klik **Jalankan Semua Tes** untuk mulai pengujian.")
    st.markdown("### 📋 Daftar Pertanyaan Uji")
    
    cats = {}
    for tid, cat, q, fn in filtered_tests:
        cats.setdefault(cat, []).append((tid, q))
    
    for cat, tests in cats.items():
        st.markdown(f"**{cat}**")
        for tid, q in tests:
            st.markdown(f"- `{tid}` {q}")
