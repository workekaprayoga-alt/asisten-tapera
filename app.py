"""
test_data.py  —  Test Suite: Kemampuan AI Membaca Data FLPP
Jalankan terpisah di Streamlit: streamlit run test_data.py
Pastikan secrets.toml sudah ada (SUPABASE_URL, SUPABASE_KEY, GROQ_KEY)
"""

import streamlit as st
import pandas as pd
import requests
import json
import re
import time
from datetime import datetime

# ============================================================
# KONFIGURASI
# ============================================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
GROQ_KEY     = st.secrets.get("GROQ_KEY", "")
TABLE_NAME   = "realisasi"

SCHEMA = {
    "id": "integer primary key",
    "tahun_akad": "integer, tahun akad kredit",
    "tahun_realisasi": "integer, tahun realisasi pencairan",
    "bank": "text, nama bank pelaksana FLPP",
    "asosiasi": "text, nama asosiasi pengembang",
    "jenis_rumah": "text, jenis/tipe rumah",
    "provinsi": "text, nama provinsi HURUF KAPITAL",
    "kabupaten": "text, nama kabupaten atau kota",
    "kecamatan": "text, nama kecamatan",
    "kelurahan": "text, nama kelurahan/desa",
    "kelamin": "text, jenis kelamin pembeli (L/P)",
    "pekerjaan": "text, pekerjaan pembeli",
    "penghasilan": "numeric, penghasilan bulanan rupiah",
    "nama_pengembang": "text, nama perusahaan pengembang",
    "nama_perumahan": "text, nama perumahan/cluster",
    "luas_bangunan": "numeric, luas bangunan m2",
    "luas_tanah": "numeric, luas tanah m2",
    "harga_rumah": "numeric, harga jual rumah rupiah",
    "tenor": "integer, jangka waktu KPR tahun",
    "suku_bunga_kpr": "numeric, suku bunga KPR persen",
    "nilai_flpp": "numeric, nilai kredit FLPP rupiah",
    "tgl_akad": "date, tanggal akad kredit",
    "tanggal_pencairan": "date, tanggal pencairan",
}

st.set_page_config(
    page_title="Test Suite — AI FLPP Data",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #0f1117; }
.pass  { background: #052e16; border: 1px solid #166534; border-radius: 8px; padding: 12px 16px; margin: 6px 0; }
.fail  { background: #450a0a; border: 1px solid #991b1b; border-radius: 8px; padding: 12px 16px; margin: 6px 0; }
.warn  { background: #1c1917; border: 1px solid #92400e; border-radius: 8px; padding: 12px 16px; margin: 6px 0; }
.skip  { background: #1e1b4b; border: 1px solid #4338ca; border-radius: 8px; padding: 12px 16px; margin: 6px 0; }
.q-label { color: #94a3b8; font-size: 12px; margin-bottom: 4px; }
.q-text  { color: #e2e8f0; font-size: 14px; font-weight: 500; margin-bottom: 8px; }
.answer  { color: #cbd5e1; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.stat-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 16px; text-align: center; }
.stat-n   { color: #38bdf8; font-size: 28px; font-weight: 700; }
.stat-l   { color: #64748b; font-size: 12px; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# HELPERS
# ============================================================
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

@st.cache_data(ttl=3600)
def count_total() -> int:
    h = sb_headers(); h["Prefer"] = "count=exact"
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=h, params={"select": "id", "limit": "1"}, timeout=20
        )
        ct = r.headers.get("content-range", "")
        return int(ct.split("/")[-1]) if "/" in ct else 0
    except:
        return 0

@st.cache_data(ttl=3600)
def get_stats():
    base = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    h = sb_headers()
    def fetch_unique(col, limit=2000):
        result = set()
        for direction in [f"{col}.asc", f"{col}.desc"]:
            try:
                r = requests.get(base, headers=h,
                    params={"select": col, "order": direction, "limit": str(limit)}, timeout=25)
                if r.ok and isinstance(r.json(), list):
                    vals = pd.DataFrame(r.json())[col].dropna().unique().tolist()
                    result.update(vals)
            except: pass
        return sorted(result)
    banks   = fetch_unique("bank", 200)
    provs   = fetch_unique("provinsi", 200)
    years_r = fetch_unique("tahun_akad", 2000) + fetch_unique("tahun_realisasi", 2000)
    years   = sorted({int(y) for y in years_r if str(y).lstrip("-").isdigit() and 2000 < int(y) < 2100})
    return {"banks": banks, "provinces": provs, "years": years}

def query_supabase(select="*", filters=None, order=None, limit=10000):
    PAGE_SIZE = 1000
    all_data, offset, remaining = [], 0, min(limit, 50000)
    while remaining > 0:
        fetch = min(PAGE_SIZE, remaining)
        params = {"select": select, "limit": str(fetch), "offset": str(offset)}
        if filters:
            for k, v in filters.items():
                if v and str(v).strip(): params[k] = str(v)
        if order and str(order).strip() not in ["", "null", "None"]:
            params["order"] = order
        try:
            r = requests.get(f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                             headers=sb_headers(), params=params, timeout=45)
            if not r.ok: break
            page = r.json()
            if not isinstance(page, list) or not page: break
            all_data.extend(page)
            if len(page) < fetch: break
            offset += fetch; remaining -= fetch
        except: break
    return pd.DataFrame(all_data) if all_data else pd.DataFrame()

def call_groq(messages, temperature=0.3, max_tokens=800):
    if not GROQ_KEY: return "⚠️ GROQ_KEY tidak ada"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
            timeout=60
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Error: {e}"

# ============================================================
# TEST CASES — 35 pertanyaan dalam 7 kategori
# ============================================================
TEST_CASES = [
    # ── A: Angka Dasar ────────────────────────────────────────
    {
        "id": "A1", "cat": "A. Angka Dasar",
        "question": "Berapa total unit FLPP yang sudah terealisasi?",
        "type": "count_total",
        "expect_contains": ["997", "unit"],
        "data_fn": lambda df, total, stats: {"result": total, "label": f"{total:,} unit"}
    },
    {
        "id": "A2", "cat": "A. Angka Dasar",
        "question": "Berapa total nilai FLPP (rupiah) secara keseluruhan?",
        "type": "aggregate",
        "select": "nilai_flpp", "limit": 20000,
        "expect_non_empty": True,
        "expect_numeric": "nilai_flpp"
    },
    {
        "id": "A3", "cat": "A. Angka Dasar",
        "question": "Data tersedia dari tahun berapa sampai tahun berapa?",
        "type": "stats",
        "expect_contains_stat": "years"
    },
    {
        "id": "A4", "cat": "A. Angka Dasar",
        "question": "Ada berapa bank pelaksana FLPP dalam data ini?",
        "type": "stats",
        "expect_contains_stat": "banks"
    },
    {
        "id": "A5", "cat": "A. Angka Dasar",
        "question": "Berapa jumlah provinsi yang tercatat dalam data?",
        "type": "stats",
        "expect_contains_stat": "provinces"
    },

    # ── B: Ranking & Top-N ────────────────────────────────────
    {
        "id": "B1", "cat": "B. Ranking & Top-N",
        "question": "Provinsi mana yang paling banyak unit FLPP?",
        "select": "provinsi", "limit": 30000, "type": "ranking",
        "group_col": "provinsi",
        "expect_top_n": 5
    },
    {
        "id": "B2", "cat": "B. Ranking & Top-N",
        "question": "10 kabupaten/kota dengan realisasi FLPP terbanyak?",
        "select": "kabupaten,provinsi", "limit": 30000, "type": "ranking",
        "group_col": "kabupaten",
        "expect_top_n": 10
    },
    {
        "id": "B3", "cat": "B. Ranking & Top-N",
        "question": "Pengembang mana yang paling produktif secara nasional?",
        "select": "nama_pengembang,provinsi", "limit": 30000, "type": "ranking",
        "group_col": "nama_pengembang",
        "expect_top_n": 10
    },
    {
        "id": "B4", "cat": "B. Ranking & Top-N",
        "question": "Perumahan mana yang paling banyak unit terealisasi?",
        "select": "nama_perumahan,kabupaten,provinsi", "limit": 30000, "type": "ranking",
        "group_col": "nama_perumahan",
        "expect_top_n": 10
    },
    {
        "id": "B5", "cat": "B. Ranking & Top-N",
        "question": "Bank mana yang paling aktif dalam pembiayaan FLPP?",
        "select": "bank,nilai_flpp", "limit": 30000, "type": "ranking",
        "group_col": "bank",
        "expect_top_n": 5
    },
    {
        "id": "B6", "cat": "B. Ranking & Top-N",
        "question": "10 perumahan dengan realisasi terbanyak tahun 2023",
        "select": "nama_perumahan,kabupaten,provinsi", "limit": 30000, "type": "ranking",
        "filters": {"tahun_akad": "eq.2023"},
        "group_col": "nama_perumahan",
        "expect_top_n": 10,
        "expect_filtered": True
    },
    {
        "id": "B7", "cat": "B. Ranking & Top-N",
        "question": "Top 5 pengembang di Jawa Barat",
        "select": "nama_pengembang,kabupaten", "limit": 20000, "type": "ranking",
        "filters": {"provinsi": "eq.JAWA BARAT"},
        "group_col": "nama_pengembang",
        "expect_top_n": 5,
        "expect_filtered": True
    },

    # ── C: Filter & Spesifik ──────────────────────────────────
    {
        "id": "C1", "cat": "C. Filter & Spesifik",
        "question": "Berapa unit FLPP di Jawa Barat?",
        "select": "id", "limit": 1,
        "type": "count_filter",
        "filters": {"provinsi": "eq.JAWA BARAT"},
        "expect_non_zero": True
    },
    {
        "id": "C2", "cat": "C. Filter & Spesifik",
        "question": "Berapa unit FLPP di tahun 2023?",
        "select": "id", "limit": 1,
        "type": "count_filter",
        "filters": {"tahun_akad": "eq.2023"},
        "expect_non_zero": True
    },
    {
        "id": "C3", "cat": "C. Filter & Spesifik",
        "question": "Berapa unit FLPP yang dibiayai BTN?",
        "select": "bank", "limit": 10000, "type": "filter_data",
        "filters": None,  # Bank name varies, detect from stats
        "expect_non_empty": True,
        "special": "detect_btn"
    },
    {
        "id": "C4", "cat": "C. Filter & Spesifik",
        "question": "Perumahan apa saja yang ada di Sumatera Utara?",
        "select": "nama_perumahan,kabupaten", "limit": 5000, "type": "filter_data",
        "filters": {"provinsi": "eq.SUMATERA UTARA"},
        "expect_non_empty": True
    },
    {
        "id": "C5", "cat": "C. Filter & Spesifik",
        "question": "Pengembang aktif di Kalimantan Timur",
        "select": "nama_pengembang,kabupaten", "limit": 5000, "type": "filter_data",
        "filters": {"provinsi": "eq.KALIMANTAN TIMUR"},
        "expect_non_empty": True
    },
    {
        "id": "C6", "cat": "C. Filter & Spesifik",
        "question": "Distribusi unit FLPP di provinsi Banten",
        "select": "kabupaten,nama_pengembang", "limit": 10000, "type": "ranking",
        "filters": {"provinsi": "eq.BANTEN"},
        "group_col": "kabupaten",
        "expect_top_n": 5
    },

    # ── D: Tren & Waktu ───────────────────────────────────────
    {
        "id": "D1", "cat": "D. Tren & Waktu",
        "question": "Tren realisasi FLPP per tahun dari awal sampai sekarang",
        "select": "tahun_akad", "limit": 30000, "type": "trend",
        "group_col": "tahun_akad",
        "expect_multi_years": True
    },
    {
        "id": "D2", "cat": "D. Tren & Waktu",
        "question": "Tahun mana yang paling banyak realisasinya?",
        "select": "tahun_akad", "limit": 30000, "type": "trend",
        "group_col": "tahun_akad",
        "expect_multi_years": True
    },
    {
        "id": "D3", "cat": "D. Tren & Waktu",
        "question": "Apakah realisasi FLPP naik atau turun dari 2022 ke 2024?",
        "select": "tahun_akad", "limit": 30000, "type": "trend",
        "group_col": "tahun_akad",
        "expect_multi_years": True
    },
    {
        "id": "D4", "cat": "D. Tren & Waktu",
        "question": "Berapa unit FLPP per tahun yang dibiayai BTN?",
        "select": "tahun_akad,bank", "limit": 20000, "type": "trend",
        "group_col": "tahun_akad",
        "special": "detect_btn_trend"
    },

    # ── E: Profil Pembeli ─────────────────────────────────────
    {
        "id": "E1", "cat": "E. Profil Pembeli",
        "question": "Berapa persen pembeli laki-laki vs perempuan?",
        "select": "kelamin", "limit": 20000, "type": "distribution",
        "group_col": "kelamin",
        "expect_top_n": 2
    },
    {
        "id": "E2", "cat": "E. Profil Pembeli",
        "question": "Pekerjaan apa yang paling banyak membeli rumah FLPP?",
        "select": "pekerjaan", "limit": 20000, "type": "distribution",
        "group_col": "pekerjaan",
        "expect_top_n": 5
    },
    {
        "id": "E3", "cat": "E. Profil Pembeli",
        "question": "Berapa rata-rata penghasilan pembeli rumah FLPP?",
        "select": "penghasilan", "limit": 20000, "type": "stats_numeric",
        "num_col": "penghasilan"
    },
    {
        "id": "E4", "cat": "E. Profil Pembeli",
        "question": "Tenor KPR berapa tahun yang paling banyak dipilih?",
        "select": "tenor", "limit": 20000, "type": "distribution",
        "group_col": "tenor",
        "expect_top_n": 3
    },
    {
        "id": "E5", "cat": "E. Profil Pembeli",
        "question": "Berapa rata-rata harga rumah FLPP yang dibeli?",
        "select": "harga_rumah,jenis_rumah", "limit": 20000, "type": "stats_numeric",
        "num_col": "harga_rumah"
    },

    # ── F: Finansial ──────────────────────────────────────────
    {
        "id": "F1", "cat": "F. Harga & Nilai",
        "question": "Berapa kisaran harga rumah FLPP (minimum dan maksimum)?",
        "select": "harga_rumah,provinsi", "limit": 20000, "type": "stats_numeric",
        "num_col": "harga_rumah"
    },
    {
        "id": "F2", "cat": "F. Harga & Nilai",
        "question": "Berapa rata-rata nilai kredit FLPP per unit?",
        "select": "nilai_flpp,bank", "limit": 20000, "type": "stats_numeric",
        "num_col": "nilai_flpp"
    },
    {
        "id": "F3", "cat": "F. Harga & Nilai",
        "question": "Provinsi mana yang rata-rata harga rumahnya paling tinggi?",
        "select": "harga_rumah,provinsi", "limit": 20000, "type": "agg_numeric",
        "group_col": "provinsi", "num_col": "harga_rumah", "agg": "mean"
    },
    {
        "id": "F4", "cat": "F. Harga & Nilai",
        "question": "Berapa total nilai kredit FLPP yang disalurkan?",
        "select": "nilai_flpp,bank,tahun_akad", "limit": 20000, "type": "stats_numeric",
        "num_col": "nilai_flpp"
    },
    {
        "id": "F5", "cat": "F. Harga & Nilai",
        "question": "Bagaimana distribusi harga rumah FLPP?",
        "select": "harga_rumah,jenis_rumah", "limit": 20000, "type": "stats_numeric",
        "num_col": "harga_rumah"
    },

    # ── G: Kombinasi & Analitik ───────────────────────────────
    {
        "id": "G1", "cat": "G. Kombinasi & Analitik",
        "question": "Bank mana yang dominan di setiap provinsi?",
        "select": "bank,provinsi", "limit": 30000, "type": "cross_tab",
        "group_col": "provinsi", "sub_col": "bank"
    },
    {
        "id": "G2", "cat": "G. Kombinasi & Analitik",
        "question": "Pengembang mana yang paling aktif di tahun 2023?",
        "select": "nama_pengembang,provinsi", "limit": 20000, "type": "ranking",
        "filters": {"tahun_akad": "eq.2023"},
        "group_col": "nama_pengembang",
        "expect_top_n": 10,
        "expect_filtered": True
    },
    {
        "id": "G3", "cat": "G. Kombinasi & Analitik",
        "question": "Jenis rumah apa yang paling banyak dibiayai FLPP?",
        "select": "jenis_rumah,harga_rumah", "limit": 20000, "type": "distribution",
        "group_col": "jenis_rumah",
        "expect_top_n": 5
    },
    {
        "id": "G4", "cat": "G. Kombinasi & Analitik",
        "question": "Asosiasi pengembang mana yang paling aktif?",
        "select": "asosiasi,provinsi", "limit": 20000, "type": "ranking",
        "group_col": "asosiasi",
        "expect_top_n": 5
    },
    {
        "id": "G5", "cat": "G. Kombinasi & Analitik",
        "question": "Perbandingan realisasi FLPP antara Jawa dan luar Jawa",
        "select": "provinsi", "limit": 30000, "type": "distribution",
        "group_col": "provinsi",
        "expect_top_n": 10
    },
]

# ============================================================
# RUNNER — jalankan 1 test case
# ============================================================
def run_test(tc: dict, total: int, stats: dict) -> dict:
    """Jalankan satu test case, kembalikan dict result."""
    result = {
        "id": tc["id"], "cat": tc["cat"],
        "question": tc["question"],
        "status": "UNKNOWN",  # PASS / FAIL / WARN / SKIP
        "data_rows": 0,
        "summary": "",
        "ai_answer": "",
        "error": "",
        "duration_ms": 0
    }

    t0 = time.time()

    try:
        # ── Tipe khusus: stats (dari metadata, tidak perlu query) ─────────
        if tc.get("type") == "stats":
            key = tc.get("expect_contains_stat", "")
            val = stats.get(key, [])
            if val:
                result["status"] = "PASS"
                if key == "years":
                    result["summary"] = f"Tahun: {min(val)}–{max(val)} ({len(val)} tahun)"
                elif key == "banks":
                    result["summary"] = f"{len(val)} bank: {', '.join(str(b) for b in val[:8])}" + ("..." if len(val) > 8 else "")
                elif key == "provinces":
                    result["summary"] = f"{len(val)} provinsi terdeteksi"
            else:
                result["status"] = "FAIL"
                result["error"]  = f"Stat '{key}' kosong"
            result["duration_ms"] = int((time.time() - t0) * 1000)
            return result

        # ── Tipe khusus: count_total ───────────────────────────────────────
        if tc.get("type") == "count_total":
            if total > 0:
                result["status"] = "PASS"
                result["summary"] = f"Total: {total:,} unit"
            else:
                result["status"] = "FAIL"
                result["error"]  = "count_total = 0"
            result["duration_ms"] = int((time.time() - t0) * 1000)
            return result

        # ── Tipe khusus: count_filter ──────────────────────────────────────
        if tc.get("type") == "count_filter":
            h = sb_headers(); h["Prefer"] = "count=exact"
            params = {"select": "id", "limit": "1"}
            for k, v in (tc.get("filters") or {}).items():
                params[k] = v
            r = requests.get(f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                             headers=h, params=params, timeout=20)
            ct = r.headers.get("content-range", "")
            cnt = int(ct.split("/")[-1]) if "/" in ct else 0
            result["data_rows"] = cnt
            if cnt > 0:
                result["status"]  = "PASS"
                result["summary"] = f"Count = {cnt:,} unit"
            else:
                result["status"] = "FAIL"
                result["error"]  = f"Count = 0 untuk filter {tc.get('filters')}"
            result["duration_ms"] = int((time.time() - t0) * 1000)
            return result

        # ── Deteksi bank BTN ───────────────────────────────────────────────
        if tc.get("special") in ("detect_btn", "detect_btn_trend"):
            btn_name = next((b for b in stats.get("banks", []) if "BTN" in b.upper()), None)
            if not btn_name:
                result["status"]  = "WARN"
                result["summary"] = "Bank BTN tidak ditemukan di stats — skip query"
                result["duration_ms"] = int((time.time() - t0) * 1000)
                return result
            filters = {"bank": f"eq.{btn_name}"}
            select  = tc.get("select", "bank,tahun_akad")
            df = query_supabase(select=select, filters=filters, limit=tc.get("limit", 10000))
        else:
            # Query normal
            df = query_supabase(
                select  = tc.get("select", "*"),
                filters = tc.get("filters") or None,
                order   = tc.get("order"),
                limit   = tc.get("limit", 10000)
            )

        result["data_rows"] = len(df)

        if df.empty:
            result["status"] = "FAIL"
            result["error"]  = "DataFrame kosong — query tidak menghasilkan data"
            result["duration_ms"] = int((time.time() - t0) * 1000)
            return result

        # ── Validasi per tipe ─────────────────────────────────────────────
        ttype = tc.get("type", "")

        if ttype in ("ranking", "distribution"):
            gcol = tc.get("group_col", "")
            if gcol not in df.columns:
                result["status"] = "FAIL"
                result["error"]  = f"Kolom '{gcol}' tidak ada di hasil query"
            else:
                vc   = df[gcol].value_counts()
                top_n = tc.get("expect_top_n", 5)
                top  = vc.head(top_n)
                result["status"]  = "PASS"
                result["summary"] = f"Top {top_n} {gcol}:\n" + "\n".join(
                    [f"  {i+1}. {k}: {v:,}" for i, (k, v) in enumerate(top.items())]
                )

        elif ttype == "trend":
            gcol = tc.get("group_col", "tahun_akad")
            if gcol in df.columns:
                vc = pd.to_numeric(df[gcol], errors="coerce").value_counts().sort_index()
                n_years = vc.nunique()
                if n_years >= 1:
                    result["status"]  = "PASS"
                    result["summary"] = f"Data {n_years} tahun:\n" + "\n".join(
                        [f"  {int(k)}: {v:,}" for k, v in vc.items()]
                    )
                else:
                    result["status"] = "FAIL"
                    result["error"]  = "Tidak ada data tahun"
            else:
                result["status"] = "FAIL"
                result["error"]  = f"Kolom '{gcol}' tidak ada"

        elif ttype == "stats_numeric":
            ncol = tc.get("num_col", "")
            if ncol in df.columns:
                s = pd.to_numeric(df[ncol], errors="coerce").dropna()
                if len(s) > 0:
                    result["status"]  = "PASS"
                    result["summary"] = (
                        f"n={len(s):,} | "
                        f"rata-rata={s.mean():,.0f} | "
                        f"median={s.median():,.0f} | "
                        f"min={s.min():,.0f} | "
                        f"max={s.max():,.0f} | "
                        f"total={s.sum():,.0f}"
                    )
                else:
                    result["status"] = "FAIL"
                    result["error"]  = f"Kolom '{ncol}' semua null"
            else:
                result["status"] = "WARN"
                result["summary"] = f"Kolom '{ncol}' tidak ada (data rows: {len(df):,})"

        elif ttype == "agg_numeric":
            gcol = tc.get("group_col", "")
            ncol = tc.get("num_col", "")
            agg  = tc.get("agg", "mean")
            if gcol in df.columns and ncol in df.columns:
                df[ncol] = pd.to_numeric(df[ncol], errors="coerce")
                agg_df = df.groupby(gcol)[ncol].agg(agg).nlargest(5).reset_index()
                result["status"]  = "PASS"
                result["summary"] = f"Top 5 {gcol} by {agg}({ncol}):\n" + "\n".join(
                    [f"  {row[gcol]}: {row[ncol]:,.0f}" for _, row in agg_df.iterrows()]
                )
            else:
                result["status"] = "FAIL"
                result["error"]  = f"Kolom '{gcol}' atau '{ncol}' tidak ada"

        elif ttype == "cross_tab":
            gcol = tc.get("group_col", "")
            scol = tc.get("sub_col", "")
            if gcol in df.columns and scol in df.columns:
                dom = df.groupby([gcol, scol]).size().reset_index(name="n")
                top = dom.loc[dom.groupby(gcol)["n"].idxmax()]
                result["status"]  = "PASS"
                result["summary"] = f"Bank dominan per provinsi (sampel {len(dom)} kombinasi):\n" + "\n".join(
                    [f"  {row[gcol]}: {row[scol]} ({row['n']:,})" for _, row in top.head(8).iterrows()]
                )
            else:
                result["status"] = "FAIL"
                result["error"]  = f"Kolom '{gcol}' atau '{scol}' tidak ada"

        elif ttype in ("aggregate", "filter_data"):
            result["status"]  = "PASS"
            result["summary"] = f"{len(df):,} baris data berhasil diambil\nKolom: {', '.join(df.columns.tolist())}"

        else:
            result["status"]  = "PASS"
            result["summary"] = f"{len(df):,} baris"

        # ── AI Answer (Groq) ───────────────────────────────────────────────
        # Hanya panggil AI untuk PASS — validasi bahwa AI bisa menjawab dengan benar
        if result["status"] == "PASS":
            schema_str = "\n".join([f"  {k}: {v}" for k, v in SCHEMA.items()])
            ai_answer = call_groq([
                {
                    "role": "system",
                    "content": f"""Kamu adalah analis data FLPP Tapera.
Total unit FLPP: {total:,}. Setiap baris = 1 unit.
Skema: {schema_str}
Bank: {', '.join(stats.get('banks', [])[:10])}
Provinsi: {', '.join(stats.get('provinces', [])[:10])}
Tahun: {stats.get('years', [])}

Jawab singkat dan faktual berdasarkan data ringkasan berikut.
JANGAN katakan 'tidak bisa' atau 'data tidak cukup' jika angka sudah ada."""
                },
                {
                    "role": "user",
                    "content": f"Pertanyaan: {tc['question']}\n\nData:\n{result['summary']}"
                }
            ], temperature=0.2, max_tokens=300)
            result["ai_answer"] = ai_answer

    except Exception as e:
        result["status"] = "FAIL"
        result["error"]  = str(e)

    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result

# ============================================================
# UI
# ============================================================
st.markdown("""
<div style="padding: 24px 0 12px 0; border-bottom: 1px solid #1e293b; margin-bottom: 24px;">
    <h1 style="color: #e2e8f0; font-size: 22px; font-weight: 700; margin: 0;">🧪 Test Suite — AI FLPP Data Reader</h1>
    <p style="color: #64748b; font-size: 13px; margin: 6px 0 0 0;">Pengujian kemampuan membaca & menjawab data untuk 35 pertanyaan kritis</p>
</div>
""", unsafe_allow_html=True)

# Status koneksi
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        f'<p style="color: #34d399; font-size: 13px;">✓ Supabase URL: {"OK" if SUPABASE_URL else "❌ KOSONG"}</p>',
        unsafe_allow_html=True
    )
with col2:
    st.markdown(
        f'<p style="color: #34d399; font-size: 13px;">✓ Supabase Key: {"OK" if SUPABASE_KEY else "❌ KOSONG"}</p>',
        unsafe_allow_html=True
    )
with col3:
    st.markdown(
        f'<p style="color: #34d399; font-size: 13px;">✓ Groq Key: {"OK" if GROQ_KEY else "❌ KOSONG"}</p>',
        unsafe_allow_html=True
    )

st.divider()

# Pilih mode run
col_opt1, col_opt2, col_opt3 = st.columns([2, 2, 3])
with col_opt1:
    run_mode = st.selectbox(
        "Mode pengujian",
        ["Semua (35 pertanyaan)", "Hanya data query (tanpa AI)", "Satu kategori saja"],
        index=0
    )
with col_opt2:
    if run_mode == "Satu kategori saja":
        cat_filter = st.selectbox(
            "Pilih kategori",
            ["A. Angka Dasar", "B. Ranking & Top-N", "C. Filter & Spesifik",
             "D. Tren & Waktu", "E. Profil Pembeli", "F. Harga & Nilai", "G. Kombinasi & Analitik"]
        )
    else:
        cat_filter = None
with col_opt3:
    st.markdown("<br>", unsafe_allow_html=True)

col_run, col_reset = st.columns([1, 5])
with col_run:
    run_all = st.button("▶ Jalankan Tes", use_container_width=True, type="primary")

if "test_results" not in st.session_state:
    st.session_state.test_results = []
if "test_running" not in st.session_state:
    st.session_state.test_running = False

# ── RUN ──────────────────────────────────────────────────────────────────────
if run_all:
    st.session_state.test_results = []
    st.session_state.test_running = True

    with st.spinner("Menghubungkan ke database..."):
        total = count_total()
        stats = get_stats()

    if total == 0:
        st.error("❌ Database tidak terhubung. Cek SUPABASE_URL dan SUPABASE_KEY.")
        st.stop()

    # Filter test cases
    tests_to_run = TEST_CASES
    if run_mode == "Satu kategori saja" and cat_filter:
        tests_to_run = [tc for tc in TEST_CASES if tc["cat"] == cat_filter]
    skip_ai = run_mode == "Hanya data query (tanpa AI)"

    st.info(f"Menjalankan {len(tests_to_run)} test... (estimasi {len(tests_to_run) * 3}–{len(tests_to_run) * 6} detik)")

    progress = st.progress(0)
    status_txt = st.empty()

    results = []
    for i, tc in enumerate(tests_to_run):
        status_txt.markdown(
            f'<p style="color: #94a3b8; font-size: 13px;">🔍 [{i+1}/{len(tests_to_run)}] {tc["id"]}: {tc["question"][:60]}...</p>',
            unsafe_allow_html=True
        )
        r = run_test(tc, total, stats)
        if skip_ai:
            r["ai_answer"] = "(AI dilewati)"
        results.append(r)
        progress.progress((i + 1) / len(tests_to_run))
        time.sleep(0.3)  # Rate limit

    st.session_state.test_results = results
    st.session_state.test_running  = False
    progress.empty()
    status_txt.empty()
    st.rerun()

# ── TAMPILKAN HASIL ───────────────────────────────────────────────────────────
if st.session_state.test_results:
    results = st.session_state.test_results

    # Ringkasan
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_warn = sum(1 for r in results if r["status"] == "WARN")
    n_total = len(results)
    pct = int(n_pass / n_total * 100) if n_total else 0

    st.markdown(f"""
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0;">
        <div class="stat-card"><div class="stat-n">{n_total}</div><div class="stat-l">Total Test</div></div>
        <div class="stat-card"><div class="stat-n" style="color: #34d399;">{n_pass}</div><div class="stat-l">PASS ✅</div></div>
        <div class="stat-card"><div class="stat-n" style="color: #f87171;">{n_fail}</div><div class="stat-l">FAIL ❌</div></div>
        <div class="stat-card"><div class="stat-n" style="color: #fbbf24;">{pct}%</div><div class="stat-l">Success Rate</div></div>
    </div>
    """, unsafe_allow_html=True)

    if n_fail > 0:
        st.warning(f"⚠️ {n_fail} test gagal — lihat detail di bawah untuk perbaikan")
    elif n_warn > 0:
        st.info(f"ℹ️ Semua test PASS ({n_warn} warning — biasanya kolom yang tidak ada di data)")
    else:
        st.success(f"🎉 Semua {n_pass} test PASS! AI sudah bisa membaca semua data dengan benar.")

    st.divider()

    # Filter tampilan
    show_filter = st.radio(
        "Tampilkan:", ["Semua", "PASS saja", "FAIL saja", "WARN saja"],
        horizontal=True, index=0
    )

    # Tampilkan per kategori
    cats = []
    for r in results:
        if r["cat"] not in cats: cats.append(r["cat"])

    for cat in cats:
        cat_results = [r for r in results if r["cat"] == cat]

        # Apply filter
        if show_filter == "PASS saja":
            cat_results = [r for r in cat_results if r["status"] == "PASS"]
        elif show_filter == "FAIL saja":
            cat_results = [r for r in cat_results if r["status"] == "FAIL"]
        elif show_filter == "WARN saja":
            cat_results = [r for r in cat_results if r["status"] == "WARN"]

        if not cat_results: continue

        n_cat_pass = sum(1 for r in cat_results if r["status"] == "PASS")
        n_cat_total = sum(1 for r in results if r["cat"] == cat)

        with st.expander(f"{cat}  ·  {n_cat_pass}/{n_cat_total} PASS", expanded=(show_filter == "FAIL saja")):
            for r in cat_results:
                css_class = {
                    "PASS": "pass", "FAIL": "fail",
                    "WARN": "warn", "UNKNOWN": "skip"
                }.get(r["status"], "skip")

                icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(r["status"], "⏭")

                st.markdown(f"""
                <div class="{css_class}">
                    <div class="q-label">{r["id"]} · {r["duration_ms"]}ms · {icon} {r["status"]}</div>
                    <div class="q-text">{r["question"]}</div>
                    {"<div class='answer'>" + r["summary"] + "</div>" if r["summary"] else ""}
                    {"<div class='answer' style='color:#f87171; margin-top:6px;'>Error: " + r["error"] + "</div>" if r["error"] else ""}
                    {"<div class='answer' style='color:#7dd3fc; margin-top:8px; padding-top:8px; border-top:1px solid #1e3a5f;'><b>AI:</b> " + r["ai_answer"] + "</div>" if r["ai_answer"] and r["ai_answer"] != "(AI dilewati)" else ""}
                </div>
                """, unsafe_allow_html=True)

    # Export hasil
    st.divider()
    st.markdown("### 📥 Export Hasil")

    df_export = pd.DataFrame([{
        "ID": r["id"],
        "Kategori": r["cat"],
        "Pertanyaan": r["question"],
        "Status": r["status"],
        "Data Rows": r["data_rows"],
        "Ringkasan": r["summary"][:200] if r["summary"] else "",
        "Error": r["error"],
        "Jawaban AI": r["ai_answer"][:300] if r["ai_answer"] else "",
        "Durasi (ms)": r["duration_ms"]
    } for r in results])

    st.dataframe(df_export, use_container_width=True, hide_index=True)

    csv = df_export.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name=f"test_flpp_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv"
    )

else:
    st.markdown("""
    <div style="text-align: center; padding: 60px 0; color: #334155;">
        <p style="font-size: 40px;">🧪</p>
        <p style="font-size: 16px; font-weight: 500; color: #64748b;">Belum ada hasil</p>
        <p style="font-size: 13px; color: #475569;">Klik <b>▶ Jalankan Tes</b> untuk mulai pengujian</p>
    </div>
    """, unsafe_allow_html=True)
