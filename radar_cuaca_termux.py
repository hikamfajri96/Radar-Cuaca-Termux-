#!/usr/bin/env python3

from __future__ import annotations
import os, sys, time, argparse, requests, re, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from shutil import which as shutil_which
import csv, glob, json, math, statistics

# optional dependency
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# ----------------- KONFIG -----------------

DATA_INDONESIA_DIR = os.getenv("DATA_INDONESIA_DIR", "./data-indonesia")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or os.getenv("BOT_TOKEN") or ""
TG_CHAT_ID = os.getenv("TG_CHAT_ID") or os.getenv("CHAT_ID") or ""
BASE_HOME = os.getenv("HOME", os.path.expanduser("~"))
LOG_DIR = os.path.join(BASE_HOME, "cuaca_logs")
os.makedirs(LOG_DIR, exist_ok=True)

REFRESH_INTERVAL_DEFAULT = 3600
MODE = "once"
COMPACT = False
SKIP_QUIET = True
MIN_REASONS_SHOW = 2
FORCE_NO_UNICODE = False
FORCE_NO_COLOR = False

# thresholds
RAWAN_RAIN_MM = 6.0
WASP_RAIN_MM = 2.0
RAWAN_HUM = 75
ACC3_RAWAN_MM = 15.0
ACC6_RAWAN_MM = 30.0
WIND_WARN = 15
WIND_DANGER = 25
GUST_WARN = 30
GUST_DANGER = 45
SCORE_HUMID_TH = 80
SCORE_TEMP_LOW = 27
SCORE_TEMP_HIGH = 34
SCORE_TEMP_DROP = 2.0
SCORE_WIND_MIN = 10
SCORE_WIND_MAX = 25
SCORE_GUST_TH = 25
SCORE_UV_TH = 7
SCORE_RAINPROB_TH = 60

THRESH_PCT = 0.8

# deviasi thresholds (std dev, mm)
DEV_WARN_TH = 0.7
DEV_DANGER_TH = 1.0

BMKG_INDEX_URL = "https://www.bmkg.go.id/alerts/nowcast/id"
PREV_TEMP_FILE = os.path.join(LOG_DIR, "prev_temp.db")

DEFAULT_LAT = {"Jakarta": -6.1754, "Bogor": -6.5971, "Depok": -6.4025, "Tangerang": -6.1275, "Bekasi": -6.2383}
DEFAULT_LON = {"Jakarta": 106.8272, "Bogor": 106.8060, "Depok": 106.7941, "Tangerang": 106.6559, "Bekasi": 106.9756}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # default model, bisa override via flag

# ---------- arg parsing ----------

parser = argparse.ArgumentParser(add_help=True)
parser.add_argument("--daemon", action="store_true")
parser.add_argument("--once", action="store_true")
parser.add_argument("--interval", type=int, default=None)
parser.add_argument("--no-unicode", action="store_true")
parser.add_argument("--no-color", action="store_true")
parser.add_argument("--compact", action="store_true")
parser.add_argument("--no-skip-quiet", action="store_true")
parser.add_argument("--level", type=str, default="", choices=["","provinsi","kabupaten","kota","kecamatan","kelurahan"],
                    help="Level administratif (opsional) — kalau dikosongkan, script coba deteksi")
parser.add_argument("--names", type=str, default="", help='Nama target (koma-sep) atau @file (file tiap baris: name[,lat,lon])')
parser.add_argument("--koordinat", type=str, default="", help='Koordinat: "label:lat,lon;lat2,lon2" atau =lat,lon')
parser.add_argument("--openai-model", type=str, default=None, help="Override OPENAI_MODEL (contoh: gpt-5-mini)")
args = parser.parse_args()

if args.daemon:
    MODE = "daemon"
if args.once:
    MODE = "once"
if args.interval:
    REFRESH_INTERVAL = args.interval
else:
    REFRESH_INTERVAL = REFRESH_INTERVAL_DEFAULT
if args.no_unicode:
    FORCE_NO_UNICODE = True
if args.no_color:
    FORCE_NO_COLOR = True
if args.compact:
    COMPACT = True
if args.no_skip_quiet:
    SKIP_QUIET = False
if args.openai_model:
    OPENAI_MODEL = args.openai_model

# ---------- TTY / warna ----------

def is_tty() -> bool:
    return sys.stdout.isatty()
_USE_COLORS = (is_tty() and not FORCE_NO_COLOR)
if _USE_COLORS:
    GREEN = "\033[1;32m"; YELLOW = "\033[1;33m"; RED = "\033[1;31m"; CYAN = "\033[1;36m"; RESET = "\033[0m"; BOLD = "\033[1m"
else:
    GREEN = YELLOW = RED = CYAN = RESET = BOLD = ""
USE_UNICODE = False if FORCE_NO_UNICODE else (is_tty() and not FORCE_NO_UNICODE)
try:
    if not FORCE_NO_UNICODE:
        "→".encode(sys.stdout.encoding or "utf-8")
        USE_UNICODE = True
except Exception:
    USE_UNICODE = False

# ---------- util ----------

WIB = timezone(timedelta(hours=7))
def now() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
def log(*args, **kwargs):
    s = " ".join(map(str,args)); line = f"[{now()}] {s}"; print(line)
    try:
        with open(os.path.join(LOG_DIR, "run.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

for c in ("curl","jq","xmlstarlet","awk","sed","grep","printf","date","bc","perl","tput"):
    if shutil_which(c) is None:
        warn_line = f"Warning: '{c}' not found. Install untuk fitur lebih lengkap."
        print(warn_line)
        try:
            with open(os.path.join(LOG_DIR, "run.log"), "a", encoding="utf-8") as f:
                f.write(f"[{now()}] {warn_line}\n")
        except:
            pass

def build_times_list() -> List[str]:
    now_dt = datetime.now(WIB).replace(minute=0, second=0, microsecond=0)
    lst = []
    for i in range(24):
        t = now_dt + timedelta(hours=i)
        lst.append(t.strftime("%Y-%m-%dT%H:00"))
    return lst
TIMES = build_times_list()

# ---------- helpers kecil ----------

def deg_to_compass_id(d: float) -> str:
    d = int(round(float(d or 0))) % 360
    if d >= 337 or d < 23: return "U"
    if 23 <= d < 68: return "TL"
    if 68 <= d < 113: return "T"
    if 113 <= d < 158: return "TG"
    if 158 <= d < 203: return "S"
    if 203 <= d < 248: return "BD"
    if 248 <= d < 293: return "B"
    return "BL"

def deg_to_arrow(d: float) -> str:
    d = int(round(float(d or 0))) % 360
    if d >= 337 or d < 23: return "↑"
    if 23 <= d < 68: return "↗"
    if 68 <= d < 113: return "→"
    if 113 <= d < 158: return "↘"
    if 158 <= d < 203: return "↓"
    if 203 <= d < 248: return "↙"
    if 248 <= d < 293: return "←"
    return "↖"

def format_temp_color(t: float) -> str:
    try: t = float(t)
    except: t = 0.0
    if t >= 33: return f"{RED}{t:.1f}°C{RESET}"
    if t < 23: return f"{CYAN}{t:.1f}°C{RESET}"
    return f"{GREEN}{t:.1f}°C{RESET}"

def format_uv_color(u: float) -> str:
    try: u = float(u)
    except: u = 0.0
    if u >= 7: return f"{RED}{u:.1f}{RESET}"
    if u >= 5: return f"{YELLOW}{u:.1f}{RESET}"
    return f"{GREEN}{u:.1f}{RESET}"

def format_wind_compact(deg: float, spd: float, gust: float) -> str:
    abbr = deg_to_compass_id(int(round(float(deg or 0)))); arrow = (deg_to_arrow(deg) + " ") if USE_UNICODE else ""
    color = GREEN
    try:
        gustv = float(gust); spdv = float(spd)
    except:
        gustv = spdv = 0.0
    if gustv >= GUST_DANGER:
        color = RED
    elif gustv >= GUST_WARN:
        color = YELLOW
    else:
        if spdv >= WIND_DANGER:
            color = RED
        elif spdv >= WIND_WARN:
            color = YELLOW
    return f"{color}{abbr}{arrow}{spdv:.0f}{RESET}"

# ---------- BMKG helpers ----------

def fetch_bmkg_index() -> List[str]:
    try:
        r = requests.get(BMKG_INDEX_URL, timeout=8); r.raise_for_status()
        html = r.text or ""
        matches = re.findall(r'href="([^"]*/alerts/nowcast/id/[^"]*_alert.xml)"', html)
        filenames = [m.split("/")[-1] for m in matches]
        return sorted(set(filenames))
    except:
        return []

def get_bmkg_code_for_city(city: str, lst: List[str]) -> str:
    city_l = city.lower()
    for f in lst:
        if city_l in f.lower():
            return f.replace("_alert.xml","")
    return ""

def fetch_bmkg_nowcast_summary(code: str) -> str:
    if not code: return ""
    urls = [f"https://www.bmkg.go.id/alerts/nowcast/id/{code}_alert.xml",
            f"https://www.bmkg.go.id/alerts/nowcast/en/{code}_alert.xml"]
    xml = ""
    for u in urls:
        try:
            r = requests.get(u, timeout=6)
            if r.ok and (r.text or "").strip():
                xml = r.text; break
        except:
            continue
    if not xml: return ""
    try:
        root = ET.fromstring(xml)
        desc = root.findtext(".//description") or ""
        event = root.findtext(".//event") or ""
        area = root.findtext(".//areaDesc") or ""
        combined = f"{event} {area} {desc}".strip()
        return re.sub(r"\s+", " ", combined)
    except:
        return ""

# ---------- kirim telegram ----------

def send_telegram(text_raw: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        try:
            with open(os.path.join(LOG_DIR, "tg_resp.log"), "a", encoding="utf-8") as f:
                f.write(f"[{now()}] send_telegram(): token/chat_id kosong — skip send\n")
        except: pass
        log("TG token atau chat_id kosong — telegram tidak dikirim.")
        return
    text_raw = text_raw.strip("\n")
    SAFELEN = 3500
    remaining = text_raw

    def try_send(chunk: str, mode: Optional[str]):
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TG_CHAT_ID, "text": chunk}
        if mode: data["parse_mode"] = mode
        try:
            r = requests.post(url, data=data, timeout=10); resp = f"{r.status_code} {r.text}"
        except Exception as e:
            resp = f"ERR {e}"
        try:
            with open(os.path.join(LOG_DIR, "tg_resp.log"), "a", encoding="utf-8") as f:
                f.write("---- TG SEND START " + now() + " ----\n"); f.write(f"MODE: {mode or 'plain'}\nLEN: {len(chunk.encode('utf-8'))}\n"); f.write("RESP: " + resp + "\n"); f.write("---- TG SEND END " + now() + " ----\n")
        except: pass
        return resp

    chunk_full = remaining[:SAFELEN]; remaining = remaining[SAFELEN:] if len(remaining) > SAFELEN else ""
    out = try_send(chunk_full, "HTML")
    if "200" in out:
        time.sleep(0.2)
        while remaining:
            chunk = remaining[:SAFELEN]; remaining = remaining[SAFELEN:] if len(remaining) > SAFELEN else ""
            try_send(chunk, None); time.sleep(0.2)
        return out
    try:
        with open(os.path.join(LOG_DIR, "tg_resp.log"), "a", encoding="utf-8") as f:
            f.write(f"[{now()}] HTML send failed, falling back to plain text.\n")
    except: pass
    remaining = text_raw
    while remaining:
        chunk = remaining[:SAFELEN]; remaining = remaining[SAFELEN:] if len(remaining) > SAFELEN else ""
        try_send(chunk, None); time.sleep(0.2)

# ---------- fetch json retry ----------

def fetch_json_retry(url: str, tries: int = 3, delay: float = 1.0) -> Optional[dict]:
    td = delay
    for i in range(tries):
        try:
            r = requests.get(url, timeout=12)
            if r.ok and r.text and r.text.strip() != "null":
                return r.json()
        except:
            pass
        time.sleep(td); td *= 2
    return None

# ---------- classifiers ----------

def classify_rain_mm(mm: float) -> str:
    try: m = float(mm)
    except: m = 0.0
    if m <= 0.0001: return "NONE"
    if m < 1.0: return "GERIMIS"
    if m < 2.5: return "RINGAN"
    if m < 7.6: return "SEDANG"
    return "DERAS"

def classify_sky(prob: float, rainmm: float, acc3: float, acc6: float, hum: float, uv: float, hour: Optional[int]) -> str:
    MIN_REALRAIN = 0.3; MIN_ACC3_FOR_HUJAN = 0.3; MIN_ACC6_FOR_HUJAN = 0.6
    ref = 0.0
    try: rainmm = float(rainmm or 0.0)
    except: rainmm = 0.0
    try: acc3 = float(acc3 or 0.0)
    except: acc3 = 0.0
    try: acc6 = float(acc6 or 0.0)
    except: acc6 = 0.0
    try: prob = float(prob or 0.0)
    except: prob = 0.0
    try: hum = float(hum or 0.0)
    except: hum = 0.0
    try: uv = float(uv or 0.0)
    except: uv = 0.0

    if rainmm >= MIN_REALRAIN: ref = rainmm
    elif acc3 >= MIN_ACC3_FOR_HUJAN: ref = acc3
    elif acc6 >= MIN_ACC6_FOR_HUJAN: ref = acc6

    if ref > 0.0001:
        if ref >= 7.6: return "HUJAN_DERAS"
        if ref >= 2.5: return "HUJAN_SEDANG"
        if ref >= 1.0: return "HUJAN_RINGAN"
        return "HUJAN_GERIMIS"
    if prob >= 60: return "HUJAN_POTENSIAL"
    is_day = False
    if hour is not None:
        try: is_day = (6 <= int(hour) <= 16)
        except: is_day = False
    if is_day and (uv >= SCORE_UV_TH and hum < RAWAN_HUM): return "CERAH"
    if (60 <= hum <= 85) and (prob < 30): return "BERAWAN"
    if (hum > RAWAN_HUM) or (30 <= prob < 60): return "MENDUNG"
    return "BERAWAN"

def add_if_not_exists(assoc: Dict[str,str], key: str, val: str):
    cur = assoc.get(key, "")
    if val not in cur.split():
        assoc[key] = (cur + " " + val).strip() if cur else val

# ----------------- parsing data-indonesia -----------------

def parse_names_arg(arg: str) -> List[str]:
    arg = arg.strip()
    if not arg: return []
    if arg.startswith("@"):
        fn = arg[1:]; out = []
        try:
            with open(fn, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    if "," in line:
                        parts = [p.strip() for p in line.split(",")]
                        out.append(parts[0])
                    else:
                        out.append(line)
            return out
        except Exception as e:
            log(f"Error membaca file names '{fn}': {e}"); return []
    return [p.strip() for p in arg.split(",") if p.strip()]

def find_level_files(level_dir: str) -> List[str]:
    out = []
    if not os.path.isdir(level_dir): return out
    patterns = ["*.csv","*.tsv","*.txt","*.json","*.sql"]
    for patt in patterns:
        out.extend(glob.glob(os.path.join(level_dir, patt)))
    out.extend(glob.glob(os.path.join(level_dir, "**", "*.csv"), recursive=True))
    seen = set(); res = []
    for f in out:
        if f not in seen:
            seen.add(f); res.append(f)
    return res

def _parse_file_to_entries(fn: str) -> List[Dict[str,str]]:
    out = []
    try:
        if fn.lower().endswith(".json"):
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict): continue
                    name = ""; lat = ""; lon = ""
                    for k,v in item.items():
                        lk = k.lower()
                        if any(tok in lk for tok in ("provinsi","kabupaten","kota","kecamatan","kelurahan","desa","nama","name")) and v:
                            name = str(v)
                        if any(tok in lk for tok in ("lat","latitude")):
                            lat = str(v)
                        if any(tok in lk for tok in ("lon","longitude","lng")):
                            lon = str(v)
                    if name:
                        out.append({"name": name.strip(), "lat": lat.strip(), "lon": lon.strip(), "source": fn})
        elif fn.lower().endswith(".sql"):
            txt = ""
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            vals = re.findall(r"VALUES\s*(.*?);", txt, flags=re.IGNORECASE | re.DOTALL)
            for v in vals:
                parts = re.findall(r"'((?:[^']|')*)'|\"((?:[^\"]|\"\")*)\"|([^\s,]+)", v)
                flat = []
                for a,b,c in parts:
                    if a: flat.append(a)
                    elif b: flat.append(b)
                    elif c: flat.append(c)
                if not flat: continue
                name = None; lat = ""; lon = ""
                for p in flat:
                    if re.match(r"^-?\d+.\d+$", p):
                        if not lat: lat = p
                        elif not lon: lon = p
                    elif not name and len(p) > 2:
                        name = p
                if name:
                    out.append({"name": name.strip(), "lat": lat.strip(), "lon": lon.strip(), "source": fn})
        else:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                sample = f.read(4096)
            delim = "\t" if ("\t" in sample and sample.count("\t") > sample.count(",")) else ","
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter=delim)
                if reader.fieldnames:
                    for row in reader:
                        lower_row = {k.lower(): (v or "") for k,v in row.items()} if row else {}
                        name = ""; lat = ""; lon = ""
                        for key in lower_row.keys():
                            if any(tok in key for tok in ("provinsi","kabupaten","kota","kecamatan","kelurahan","desa","nama","name")) and lower_row.get(key):
                                name = lower_row.get(key)
                            if any(tok in key for tok in ("lat","latitude")) and lower_row.get(key):
                                lat = lower_row.get(key)
                            if any(tok in key for tok in ("lon","longitude","lng")) and lower_row.get(key):
                                lon = lower_row.get(key)
                        if not name:
                            if reader.fieldnames and len(reader.fieldnames) > 0:
                                first = reader.fieldnames[0]
                                val = row.get(first)
                                if val:
                                    name = val
                        if name:
                            out.append({"name": str(name).strip(), "lat": str(lat).strip(), "lon": str(lon).strip(), "source": fn})
                else:
                    f.seek(0)
                    for line in f:
                        s = line.strip()
                        if not s: continue
                        parts = [p.strip() for p in re.split(r"[,\t;]+", s) if p.strip()]
                        if not parts: continue
                        name = parts[0]; lat = parts[1] if len(parts) > 1 else ""; lon = parts[2] if len(parts) > 2 else ""
                        out.append({"name": name, "lat": lat, "lon": lon, "source": fn})
    except Exception:
        pass
    return out

def load_level_entries(level: str) -> List[Dict[str,str]]:
    level = level.lower(); base = DATA_INDONESIA_DIR; entries: List[Dict[str,str]] = []
    if level == "provinsi":
        candidates = [os.path.join(base, "provinsi.csv"), os.path.join(base, "provinsi.json")]
    elif level == "kota":
        candidates = [os.path.join(base, "kota"), os.path.join(base, "kota.csv"), os.path.join(base, "kota.json")]
    elif level == "kabupaten":
        candidates = [os.path.join(base, "kabupaten"), os.path.join(base, "kabupaten.csv"), os.path.join(base, "kabupaten.json")]
    elif level == "kecamatan":
        candidates = [os.path.join(base, "kecamatan"), os.path.join(base, "kecamatan.csv"), os.path.join(base, "kecamatan.json")]
    else:
        candidates = [os.path.join(base, "kelurahan"), os.path.join(base, "kelurahan.csv"), os.path.join(base, "kelurahan.json")]
    for c in candidates:
        if os.path.isdir(c):
            files = find_level_files(c)
            for fn in files:
                entries.extend(_parse_file_to_entries(fn))
        elif os.path.isfile(c):
            entries.extend(_parse_file_to_entries(c))
    seen = set(); out = []
    for e in entries:
        n = (e.get("name") or "").strip()
        if not n: continue
        key = n.lower()
        if key in seen: continue
        seen.add(key); out.append(e)
    return out

def find_matches(query_names: List[str], db_entries: List[Dict[str,str]]) -> List[Tuple[str,float,float]]:
    results = []
    db_map = {e["name"].strip().lower(): e for e in db_entries}
    lower_names = [e["name"].strip().lower() for e in db_entries]
    for q in query_names:
        ql = q.strip().lower()
        if not ql: continue
        if ql in db_map:
            e = db_map[ql]
            try:
                lat = float(e.get("lat") or 0.0); lon = float(e.get("lon") or 0.0)
            except:
                lat = lon = 0.0
            results.append((e["name"].strip(), lat, lon)); continue
        found = None
        for name in lower_names:
            if ql in name:
                found = db_map[name]; break
        if found:
            try:
                lat = float(found.get("lat") or 0.0); lon = float(found.get("lon") or 0.0)
            except:
                lat = lon = 0.0
            results.append((found["name"].strip(), lat, lon)); continue
        log(f"Target '{q}' tidak ditemukan di DB lokal ({DATA_INDONESIA_DIR})")
    return results

# ---------- koordinat parser ----------

def parse_koordinat_arg(arg: str) -> List[Tuple[str,float,float]]:
    arg = arg.strip()
    if not arg: return []
    parts = re.split(r"[;|]+", arg); out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        if ":" in p: lab, coords = p.split(":",1)
        else: lab = ""; coords = p
        coords = coords.strip()
        m = re.match(r"(-?\d+.\d+)\s*,\s*(-?\d+.\d+)$", coords)
        if not m:
            log(f"Invalid koordinat format: {p}")
            continue
        lat = float(m.group(1)); lon = float(m.group(2))
        label = lab.strip() if lab.strip() else f"{lat:.6f},{lon:.6f}"
        out.append((label, lat, lon))
    return out

# ---------- prev temp ----------

def load_prev_temp_file() -> Dict[str,str]:
    data: Dict[str,str] = {}
    if not os.path.exists(PREV_TEMP_FILE): return data
    try:
        with open(PREV_TEMP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s: continue
                parts = s.split("|",1)
                if len(parts) == 2:
                    key, val = parts[0].strip(), parts[1].strip()
                    if key and val:
                        data[key] = val
    except Exception:
        pass
    return data

def save_prev_temp_file(store: Dict[str,str]):
    try:
        with open(PREV_TEMP_FILE, "w", encoding="utf-8") as f:
            for k,v in store.items():
                f.write(f"{k}|{v}\n")
    except Exception:
        pass

def lookup_prev_temp_for(name: str, lat: float, lon: float, prev_map: Dict[str,str]) -> Optional[str]:
    if not prev_map: return None
    key_name = name.strip()
    key_latlon = f"{float(lat):.4f},{float(lon):.4f}"
    if key_name in prev_map: return prev_map[key_name]
    if key_latlon in prev_map: return prev_map[key_latlon]
    for k in prev_map.keys():
        if key_name.lower() == k.lower(): return prev_map[k]
    return None

# ---------- summarizer lokal (fallback NON-AI lengkap) ----------

def local_ai_summarize(per_location, best_aman_times, any_rawan_times, update_ts):
    out = []
    out.append("Prakiraan (24h)")
    out.append(f"Update: {update_ts}\n")
    # Jam aman & berisiko global
    aman_jam = ", ".join(best_aman_times) if best_aman_times else "Tidak terdeteksi"
    rawan_jam = ", ".join(any_rawan_times) if any_rawan_times else "Tidak terdeteksi"
    out.append(f"Jam paling AMAN (semua lokasi Aman >= threshold): {aman_jam}")
    out.append(f"Jam berisiko hujan (>=2 lokasi): {rawan_jam}")
    # Global thunderstorm (default kalau gak ada data)
    out.append("Potensi badai/petir (waktu): Tidak terdeteksi")
    # Gust & angin (cari keys fallback jika ada)
    gust_waspada = per_location.get("_gust_waspada", []) if isinstance(per_location, dict) else []
    angin_waspada = per_location.get("_angin_waspada", []) if isinstance(per_location, dict) else []
    out.append("Jam gust waspada (≥30 km/h): " + (", ".join(gust_waspada) if gust_waspada else ""))
    out.append("Jam gust berbahaya (≥45 km/h): Tidak terdeteksi")
    out.append("Jam angin sustained waspada/kencang (15/25 km/h): " + (", ".join(angin_waspada) if angin_waspada else "") + " / Tidak terdeteksi\n")
    out.append("Potensi badai/petir per lokasi:")
    for loc in per_location.keys():
        if loc.startswith("_"): continue
        vals = per_location.get(loc, {}).get("thunder_times") or []
        out.append(f"{loc}: {', '.join(vals) if vals else 'Tidak terdeteksi'}")
    out.append("")
    out.append("Ringkasan langit per lokasi:")
    for loc, info in per_location.items():
        if loc.startswith("_"): continue
        info = info or {}
        sky_summary = info.get("sky_summary") or {}
        if sky_summary:
            seg = ", ".join([f"{k}={v}j" for k, v in sky_summary.items()])
            out.append(f"{loc}: {seg}")
            continue
        jam = info.get("per_jam", {}) or {}
        sky_count = {
            "cerah": 0,
            "berawan": 0,
            "mendung": 0,
            "hujan gerimis": 0,
            "hujan ringan": 0,
            "hujan sedang": 0,
            "hujan deras": 0
        }
        for t, rec in jam.items():
            kond = (rec.get("sky") or "").strip().lower().replace("_", " ").replace("-", " ")
            if not kond:
                continue
            if kond in sky_count:
                sky_count[kond] += 1; continue
            if "gerimis" in kond:
                sky_count["hujan gerimis"] += 1
            elif "ringan" in kond and "hujan" in kond:
                sky_count["hujan ringan"] += 1
            elif "sedang" in kond and "hujan" in kond:
                sky_count["hujan sedang"] += 1
            elif "deras" in kond or "keras" in kond:
                sky_count["hujan deras"] += 1
            elif "cerah" in kond:
                sky_count["cerah"] += 1
            elif "berawan" in kond:
                sky_count["berawan"] += 1
            else:
                sky_count["berawan"] += 1
        hasil = [f"{k}={v}j" for k, v in sky_count.items() if v > 0]
        seg = ", ".join(hasil) if hasil else "Tidak ada data"
        out.append(f"{loc}: {seg}")
    out.append("")
    # Risiko hujan nyata per lokasi (>=0.3 mm/jam)
    out.append("Risiko hujan nyata per lokasi (>=0.3 mm/jam):")
    for loc, info in per_location.items():
        if loc.startswith("_"): continue
        info = info or {}
        risk = info.get("realrain_events") or []
        if not risk:
            out.append(f"{loc}: Tidak terdeteksi")
        else:
            jamlist = ", ".join([f"{t} ({typ})" for t, typ in [(r, r.split(":")[-1]) for r in risk]])
            out.append(f"{loc}: {len(risk)} jam -> {jamlist}")
    out.append("")
    # Tambah ringkasan deviasi per lokasi
    out.append("Ringkasan deviasi per lokasi (std dev 3-jam curah hujan, mm):")
    for loc, info in per_location.items():
        if loc.startswith("_"): continue
        devtimes = info.get("dev_times") or []
        dev_sample = info.get("dev_sample_mm")
        if devtimes:
            out.append(f"{loc}: dev warning/danger pada {', '.join(devtimes)} (sample={dev_sample})")
        else:
            out.append(f"{loc}: Tidak terdeteksi deviasi tinggi (sample={dev_sample})")
    out.append("")
    return "\n".join(out)

# ----------------- OPENAI helper (auto endpoint selection) -----------------
def _model_looks_like_responses(model_name: str) -> bool:
    if not model_name: return False
    mn = model_name.lower()
    if "gpt-5.1" in mn: return True
    if mn in ["gpt-5","gpt-5-large","gpt-5.1-large","gpt-5.1"]: return True
    return False

def openai_request(system_prompt: str, user_prompt: str, model: str = None, max_tokens: int = 350, temperature: float = 0.6) -> str:
    """Unified OpenAI caller. Memilih endpoint /v1/responses atau /v1/chat/completions.
    Mengembalikan teks hasil (string). Jika gagal, kembalikan empty string.
    """
    if not model:
        model = OPENAI_MODEL or "gpt-4o-mini"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    try:
        use_responses = _model_looks_like_responses(model)
        if use_responses:
            body = {
                "model": model,
                "input": (system_prompt or "") + "\n\n" + (user_prompt or ""),
                "max_output_tokens": max_tokens,
                "temperature": temperature
            }
            r = requests.post("https://api.openai.com/v1/responses", headers=headers, json=body, timeout=30)
            r.raise_for_status()
            j = r.json()
            out_txt = ""
            try:
                if "output" in j and isinstance(j["output"], list):
                    parts = []
                    for item in j["output"]:
                        if isinstance(item, dict):
                            cont = item.get("content")
                            if isinstance(cont, list):
                                for c in cont:
                                    if isinstance(c, dict) and "text" in c:
                                        parts.append(c.get("text", ""))
                                    elif isinstance(c, str):
                                        parts.append(c)
                            elif isinstance(cont, str):
                                parts.append(cont)
                        elif isinstance(item, str):
                            parts.append(item)
                    out_txt = "\n".join([p for p in parts if p])
                if not out_txt and "choices" in j and isinstance(j["choices"], list):
                    out_txt = j["choices"][0].get("message", {}).get("content", "")
                if not out_txt:
                    out_txt = json.dumps(j, ensure_ascii=False)
            except Exception:
                out_txt = ""
            return out_txt.strip()
        else:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=30)
            r.raise_for_status()
            j = r.json()
            content = j.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return content
    except Exception as e:
        try:
            log("openai_request gagal: " + str(e))
        except: pass
        return ""

# ---------- AI summarizer (OpenAI) with fallback ke local ----------

def ai_summarize_weather_structured(per_location: dict, best_aman_times: List[str], any_rawan_times: List[str], update_ts: str) -> str:
    # Jika tidak ada API key, fallback ke local summarizer
    if not OPENAI_API_KEY:
        return local_ai_summarize(per_location, best_aman_times, any_rawan_times, update_ts)

    system_prompt = (
        "Kamu bikin ringkasan cuaca untuk driver ojek online. "
        "Gaya ngomong santai, ceplas-ceplos, kayak abang ojol ngobrol di WhatsApp. "
        "Jangan kaku, jangan baku. "
        "Setiap kota 1 baris: 'Kota suhu — komentar santai'. "
        "Komentarmu boleh pakai frasa ringan seperti: aman bro, masih gas, agak gerah, rada lembap, "
        "belum ada tanda hujan, hati-hati dikit, UV lagi nakal, angin lumayan, dst. "
        "Cukup sebut 1–2 info penting: berawan/mendung, peluang hujan (kecil/sedang), angin (pelan/sedang), UV (sedang/tinggi). "
        "Tambahkan jika ada jam deviasi (std dev curah hujan) yang waspada/berbahaya. "
        "Jika ada deviasi, sebutkan 'deviasi' singkat pada kota yang terkena. "
        "Emoji maksimal 1 per kota. "
        "Setelah semua kota, buat 2 baris ringkasan:"
        "'Jam paling aman narik: ...'"
        "dan"
        "'Jam berisiko: ...'. "
        "Total maksimal 10 baris."
    )

    payload_context = {
        "update": update_ts,
        "best_aman_times": best_aman_times,
        "any_rawan_times": any_rawan_times,
        "locations": per_location
    }

    user_prompt = (
        "Ini data JSON lengkapnya. Ambil suhu, langit, peluang hujan, angin, UV, dan deviasi dari data di bawah. "
        "TAPI tampilkan hanya hal yang penting. "
        "Jangan mengulang parameter tidak penting, jangan kaku seperti laporan cuaca. "
        "Gunakan gaya santai ala abang ojol.\n\n"
        + json.dumps(payload_context, ensure_ascii=False)
    )

    content = openai_request(system_prompt, user_prompt, model=OPENAI_MODEL, max_tokens=1000, temperature=0.45)
    if not content:
        return local_ai_summarize(per_location, best_aman_times, any_rawan_times, update_ts)
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if len(lines) > 10:
        lines = lines[:10]
    return "\n".join(lines)

# ------------------ NEW: generate_conclusion (AI-first, fallback lokal) ------------------

def generate_conclusion(per_loc_struct: dict, processed_locations_list: list, best_aman_times: list, any_rawan_times: list, update_ts: str) -> str:
    def local_kesimpulan():
        rawan_list, wasp_list, aman_list = [], [], []
        for k in processed_locations_list:
            info = per_loc_struct.get(k, {}) or {}
            has_rawan = bool(info.get("rawan_times")) or bool(info.get("realrain_events")) or bool(info.get("thunder_times"))
            has_wasp = bool(info.get("wasp_rain_times")) or bool(info.get("wasp_heat_times")) or bool(info.get("wasp_gust_times")) or bool(info.get("dev_times"))
            if has_rawan:
                rawan_list.append(k)
            elif has_wasp:
                wasp_list.append(k)
            else:
                aman_list.append(k)

        parts = []
        if rawan_list:
            parts.append(f"{', '.join(rawan_list)} rawan — jangan ambil order berat, terutama pas hujan/petir.")
        if wasp_list:
            parts.append(f"{', '.join(wasp_list)} waspada — siapin jas hujan & cek kondisi jalan.")
        if aman_list:
            parts.append(f"{', '.join(aman_list)} masih bisa narik, tapi tetep awas.")
        if parts:
            return "Kesimpulan tegasnya: " + " ".join(parts)
        return "Kesimpulan tegasnya: Semua lokasi relatif aman — masih bisa narik normal."

    try:
        if not OPENAI_API_KEY:
            return local_kesimpulan()
    except:
        return local_kesimpulan()

    summary_context = {
        "update": update_ts,
        "best_aman": best_aman_times,
        "rawan_times": any_rawan_times,
        "lokasi": {}
    }

    for k in processed_locations_list:
        info = per_loc_struct.get(k, {}) or {}
        summary_context["lokasi"][k] = {
            "rawan": bool(info.get("rawan_times")) or bool(info.get("realrain_events")) or bool(info.get("thunder_times")),
            "waspada": bool(info.get("wasp_rain_times")) or bool(info.get("wasp_heat_times")) or bool(info.get("wasp_gust_times")) or bool(info.get("dev_times")),
            "realrain": len(info.get("realrain_events") or []),
            "thunder": bool(info.get("thunder_times")),
            "dev": len(info.get("dev_times") or []),
            "dev_sample_mm": info.get("dev_sample_mm")
        }

    system_msg = (
    "Kamu bikin ringkasan tegas untuk driver ojol. "
    "Nada abang ojol senior: santai, ceplas-ceplos, tapi sopan. "
    "Baca semua datanya dari awal sampai akhir dan analisa secara mendalam dan akurat. "
    "Buat maksimal 2-3 paragraf saja, dimulai dengan 'Kesimpulan tegasnya:'. "
    "Tidak pakai emoji. "
    "Gak usah bertele-tele, berikan kepastian apakah sekarang dan untuk 3 dan 6 jam kedepan aman atau turun hujan, singkat padat dan jelas."
    "Tentukan kota atau lokasi mana saja yang berpotensi hujan dengan waktunya secara presisi dan akurat, apakah hujan turun sesuai data atau bergeser maju atau mundur dari datanya. "
    "Sertakan juga sumber data dan berapa persen akurasinya, di awali dengan kalimat 'Sumber data:', dan 'Persentase akurasi data:'. "
)

    user_msg = "Konteks:\n" + json.dumps(summary_context, ensure_ascii=False)

    txt = openai_request(system_msg, user_msg, model=OPENAI_MODEL, max_tokens=900, temperature=0.45)
    if not txt:
        return local_kesimpulan()
    if not txt.lower().startswith("kesimpulan tegas"):
        txt = "Kesimpulan tegasnya: " + txt
    return " ".join(txt.split())

# ----------------- main run_once -----------------

def run_once():
    TIMESTAMP_NOW = now(); log("Update terakhir: " + TIMESTAMP_NOW)
    log("Menjalankan prakiraan cuaca (24 jam)")
    PREV_TEMP = load_prev_temp_file()

    LAT = dict(DEFAULT_LAT); LON = dict(DEFAULT_LON)

    # koordinat explicit override
    if args.koordinat:
        parsed = parse_koordinat_arg(args.koordinat)
        if parsed:
            LAT = {}; LON = {}
            for label, latv, lonv in parsed:
                LAT[label] = latv; LON[label] = lonv
            log(f"Koordinat dipakai: {', '.join(list(LAT.keys()))}")
    # names -> coba DB -> jika gak ketemu fallback ke DEFAULT
    elif args.names:
        qnames = parse_names_arg(args.names)
        if qnames:
            db = load_level_entries(args.level)
            log(f"Level: {args.level}. Entri DB ditemukan: {len(db)}")
            matches = find_matches(qnames, db)
            match_map = {name.strip().lower(): (lat, lon) for (name, lat, lon) in matches}
            LAT = {}; LON = {}
            skipped = []
            for q in qnames:
                ql = q.strip().lower()
                if ql in match_map:
                    latv, lonv = match_map[ql]
                    if latv == 0.0 and lonv == 0.0:
                        skipped.append(q); continue
                    LAT[q] = float(latv); LON[q] = float(lonv)
                else:
                    found_default = None
                    for dk in DEFAULT_LAT.keys():
                        if dk.lower() == ql:
                            found_default = dk; break
                    if found_default:
                        LAT[found_default] = DEFAULT_LAT[found_default]; LON[found_default] = DEFAULT_LON[found_default]
                        log(f"Fallback ke DEFAULT coordinates untuk '{q}' -> {found_default}")
                    else:
                        skipped.append(q)
            if not LAT:
                log("Tidak ada target ditemukan/valid. Menggunakan default 5 kota.")
                LAT = dict(DEFAULT_LAT); LON = dict(DEFAULT_LON)
            else:
                log(f"Target dipakai: {', '.join(list(LAT.keys()))}")
                if skipped:
                    log(f"Target tanpa koordinat/ditemukan (dilewati): {', '.join(skipped)}")

    bmkg_file_list = fetch_bmkg_index()
    BMKG_CODE: Dict[str,str] = {}
    for C in list(LAT.keys()):
        BMKG_CODE[C] = get_bmkg_code_for_city(C, bmkg_file_list)

    AGG_AMAN = {t:0 for t in TIMES}; AGG_WASP = {t:0 for t in TIMES}; AGG_RAWAN = {t:0 for t in TIMES}
    AGG_THUNDER = {t:0 for t in TIMES}; AGG_WIND_WARN = {t:0 for t in TIMES}; AGG_WIND_DANGER = {t:0 for t in TIMES}
    AGG_GUST_WARN = {t:0 for t in TIMES}; AGG_GUST_DANGER = {t:0 for t in TIMES}
    AGG_RAIN_GERIMIS = {t:0 for t in TIMES}; AGG_RAIN_RINGAN = {t:0 for t in TIMES}; AGG_RAIN_SEDANG = {t:0 for t in TIMES}; AGG_RAIN_DERAS = {t:0 for t in TIMES}
    AGG_DEV_WARN = {t:0 for t in TIMES}; AGG_DEV_DANGER = {t:0 for t in TIMES}

    PERKOTA_THUNDER = {}; PERKOTA_RAWAN = {}; PERKOTA_WASP_RAIN = {}; PERKOTA_WASP_HEAT = {}
    PERKOTA_WASP_GUST = {}
    PERKOTA_RAIN_GERIMIS = {}; PERKOTA_RAIN_RINGAN = {}; PERKOTA_RAIN_SEDANG = {}; PERKOTA_RAIN_DERAS = {}; PERKOTA_REALRAIN = {}
    PERKOTA_DEV_WARN = {}; PERKOTA_DEV_DANGER = {}
    SKY_COUNT: Dict[str, Dict[str,int]] = {}
    PER_LOC_SAMPLE: Dict[str, Dict[str,Optional[float]]] = {}

    processed_count = 0; processed_locations_list: List[str] = []

    for K in list(LAT.keys()):
        LATK = LAT[K]; LONK = LON[K]; BMKCODE = BMKG_CODE.get(K,"")
        if LATK is None or LONK is None:
            log(f"Lokasi {K} dilewati (koordinat tidak valid)."); continue

        # -------------- FETCH DETERMINISTIC FORECAST --------------
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LATK}&longitude={LONK}"
            "&hourly=temperature_2m,precipitation,precipitation_probability,relative_humidity_2m,windspeed_10m,winddirection_10m,windgusts_10m,uv_index"
            "&timezone=Asia%2FJakarta&windspeed_unit=kmh"
        )
        DATA = fetch_json_retry(url)
        if DATA is None:
            log(f"Gagal ambil Open-Meteo untuk {K}"); continue

        # -------------- FETCH ENSEMBLE (Open-Meteo Ensemble API) --------------
        # ADDED: call ensemble endpoint once per location to compute ensemble deviasi 3-hr (member accumulated sums)
        ensemble_available = False
        ensemble_members = []  # list of numpy-like lists per member
        ensemble_times = []
        ensemble_members_raw = {}  # keep raw arrays if needed
        try:
            ens_url = (
                "https://ensemble-api.open-meteo.com/v1/ensemble"
                f"?latitude={LATK}&longitude={LONK}"
                "&models=gfs_seamless"
                "&hourly=rain"
                "&forecast_days=2"
                "&timezone=Asia%2FJakarta"
            )
            ENS_DATA = fetch_json_retry(ens_url)
            # ENS_DATA is usually a list (per location) — handle both
            ens_obj = None
            if ENS_DATA:
                if isinstance(ENS_DATA, list):
                    ens_obj = ENS_DATA[0]
                elif isinstance(ENS_DATA, dict):
                    ens_obj = ENS_DATA
            if ens_obj and "hourly" in ens_obj:
                hourly_ens = ens_obj["hourly"]
                # detect member keys rain_member01...
                member_keys = sorted([k for k in hourly_ens.keys() if k.startswith("rain_member")])
                if member_keys:
                    ensemble_available = True
                    # build member lists
                    for m in member_keys:
                        arr = hourly_ens.get(m, [])
                        ensemble_members.append([float(x) if x is not None else 0.0 for x in arr])
                        ensemble_members_raw[m] = hourly_ens.get(m, [])
                    ensemble_times = hourly_ens.get("time", [])
        except Exception:
            ensemble_available = False

        processed_count += 1; processed_locations_list.append(K)
        BMK_SUM = fetch_bmkg_nowcast_summary(BMKCODE) if BMKCODE else ""

        print(f"{BOLD}{CYAN}{K}{RESET}")
        if COMPACT:
            print("-"*111)
            print("{:<16} | {:<8} | {:<9} | {:<9} | {:<8} | {:<13} | {:<7} | {:<6} | {:<10} | {:<9} | {:<20}".format(
                "Tanggal-Jam","Suhu","Hujan(%)","Hujan(mm)","Lembap","Dev(mm)","Angin","Gust","UV","Langit","Status"))
            print("-"*111)
        else:
            print("-"*200)
            print("{:<16} | {:<8} | {:<9} | {:<9} | {:<8} | {:<8} | {:<8} | {:<13} | {:<7} | {:<6} | {:<10} | {:<9} | {:<20}".format(
                "Tanggal-Jam","Suhu","Hujan(%)","Hujan(mm)","Acc3mm","Acc6mm","Lembap(%)","Dev(mm)","Angin (km/h)","Gust","UV","Langit","Status"))
            print("-"*200)

        times_jq = DATA.get("hourly", {}).get("time", [])
        temp_arr = DATA.get("hourly", {}).get("temperature_2m", [])
        pop_arr = DATA.get("hourly", {}).get("precipitation_probability", [])
        prec_arr = DATA.get("hourly", {}).get("precipitation", [])
        hum_arr = DATA.get("hourly", {}).get("relative_humidity_2m", [])
        wind_arr = DATA.get("hourly", {}).get("windspeed_10m", [])
        wdir_arr = DATA.get("hourly", {}).get("winddirection_10m", [])
        gust_arr = DATA.get("hourly", {}).get("windgusts_10m", [])
        uv_arr = DATA.get("hourly", {}).get("uv_index", [])
        LEN = len(times_jq)

        aman = wasp = rawan = 0
        PERKOTA_THUNDER[K] = ""; PERKOTA_RAWAN[K] = ""; PERKOTA_WASP_RAIN[K] = ""; PERKOTA_WASP_HEAT[K] = ""
        PERKOTA_WASP_GUST[K] = ""; PERKOTA_RAIN_GERIMIS[K] = ""; PERKOTA_RAIN_RINGAN[K] = ""; PERKOTA_RAIN_SEDANG[K] = ""; PERKOTA_RAIN_DERAS[K] = ""
        PERKOTA_REALRAIN[K] = ""; SKY_COUNT[K] = {}
        PERKOTA_DEV_WARN[K] = ""; PERKOTA_DEV_DANGER[K] = ""

        for TIME in TIMES:
            try: idx = times_jq.index(TIME)
            except ValueError: continue

            SUHU = temp_arr[idx] if idx < len(temp_arr) else 0.0
            HUJAN_PROB = pop_arr[idx] if idx < len(pop_arr) else 0.0
            RAINMM = prec_arr[idx] if idx < len(prec_arr) else 0.0
            LEMBAP = hum_arr[idx] if idx < len(hum_arr) else 0.0
            ANGIN = wind_arr[idx] if idx < len(wind_arr) else 0.0
            WDIR_DEG = wdir_arr[idx] if idx < len(wdir_arr) else 0.0
            WINDGUST = gust_arr[idx] if idx < len(gust_arr) else 0.0
            UV = uv_arr[idx] if idx < len(uv_arr) else 0.0

            # acc3 / acc6
            acc3 = 0.0
            for j in (0,1,2):
                if idx + j < LEN:
                    try: acc3 += float(prec_arr[idx+j])
                    except: pass
            acc6 = 0.0
            for j in range(6):
                if idx + j < LEN:
                    try: acc6 += float(prec_arr[idx+j])
                    except: pass

            # ----- DEV: std dev on 3-hour window (current + next 2) - DETERMINISTIC (existing)
            dev_mm = 0.0
            try:
                window_vals = []
                for j in (0,1,2):
                    if idx + j < LEN:
                        try:
                            v = float(prec_arr[idx+j])
                            window_vals.append(v)
                        except:
                            pass
                if len(window_vals) >= 2:
                    dev_mm = statistics.pstdev(window_vals)  # population stdev to keep scale stable
                else:
                    dev_mm = 0.0
            except Exception:
                dev_mm = 0.0

            # ----- DEV (ENSEMBLE): compute 3-hour accumulated sums per member and stddev across members
            dev_ens_3hr = 0.0
            try:
                if ensemble_available and ensemble_members:
                    member_sums = []
                    for mem in ensemble_members:
                        # mem is a list of hourly rain values (len may differ). compute sum over idx..idx+2
                        s = 0.0
                        for j in (0,1,2):
                            if idx + j < len(mem):
                                try:
                                    s += float(mem[idx + j] or 0.0)
                                except:
                                    pass
                        member_sums.append(s)
                    if len(member_sums) >= 2:
                        dev_ens_3hr = statistics.pstdev(member_sums)
                    else:
                        dev_ens_3hr = 0.0
                else:
                    dev_ens_3hr = 0.0
            except Exception:
                dev_ens_3hr = 0.0

            REASONS = []
            if float(RAINMM) > 0.0001: rain_ref_for_cat = float(RAINMM)
            elif acc3 > 0.0001: rain_ref_for_cat = acc3
            else: rain_ref_for_cat = acc6
            rain_cat = classify_rain_mm(rain_ref_for_cat)
            if rain_cat == "GERIMIS":
                PERKOTA_RAIN_GERIMIS[K] = (PERKOTA_RAIN_GERIMIS[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_RAIN_GERIMIS[K] else TIME.replace("T"," ")
                AGG_RAIN_GERIMIS[TIME] += 1; REASONS.append("rain_gerimis")
            elif rain_cat == "RINGAN":
                PERKOTA_RAIN_RINGAN[K] = (PERKOTA_RAIN_RINGAN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_RAIN_RINGAN[K] else TIME.replace("T"," ")
                AGG_RAIN_RINGAN[TIME] += 1; REASONS.append("rain_ringan")
            elif rain_cat == "SEDANG":
                PERKOTA_RAIN_SEDANG[K] = (PERKOTA_RAIN_SEDANG[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_RAIN_SEDANG[K] else TIME.replace("T"," ")
                AGG_RAIN_SEDANG[TIME] += 1; REASONS.append("rain_sedang")
            elif rain_cat == "DERAS":
                PERKOTA_RAIN_DERAS[K] = (PERKOTA_RAIN_DERAS[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_RAIN_DERAS[K] else TIME.replace("T"," ")
                AGG_RAIN_DERAS[TIME] += 1; REASONS.append("rain_keras")

            HOUR = int(TIME.split("T")[1][:2])
            SKY_LABEL = classify_sky(HUJAN_PROB, RAINMM, acc3, acc6, LEMBAP, UV, HOUR)
            SKY_DISPLAY = SKY_LABEL.lower().replace("_"," ")
            SKY_TOKEN = SKY_LABEL.lower().replace("_"," ").replace(" ","_")
            SKY_COUNT[K][SKY_DISPLAY] = SKY_COUNT[K].get(SKY_DISPLAY,0) + 1
            REASONS.insert(0, f"sky_{SKY_TOKEN}")

            if float(RAINMM) >= 0.3:
                entry = f"{TIME.replace('T',' ')}:{rain_cat}"
                if entry not in PERKOTA_REALRAIN[K].splitlines():
                    PERKOTA_REALRAIN[K] = (PERKOTA_REALRAIN[K] + "\n" + entry).strip() if PERKOTA_REALRAIN[K] else entry

            score = 0
            if float(LEMBAP) > SCORE_HUMID_TH: score += 2; REASONS.append("humid")
            if SCORE_TEMP_LOW <= float(SUHU) <= SCORE_TEMP_HIGH: score += 1; REASONS.append("temp_ok")
            prev = lookup_prev_temp_for(K, LATK, LONK, PREV_TEMP)
            if prev:
                try:
                    if (float(prev) - float(SUHU)) >= SCORE_TEMP_DROP:
                        score += 2; REASONS.append("temp_drop")
                except: pass
            if SCORE_WIND_MIN <= float(ANGIN) <= SCORE_WIND_MAX: score += 1; REASONS.append("wind_ok")
            if float(WINDGUST) > SCORE_GUST_TH: score += 1; REASONS.append("gust")
            if 8 <= HOUR <= 16:
                if float(UV) >= SCORE_UV_TH: score += 2; REASONS.append("uv_high")
            if float(HUJAN_PROB) >= 70: score += 2; REASONS.append("prob>=70")
            elif float(HUJAN_PROB) >= 50: score += 1; REASONS.append("prob>=50")
            if float(RAINMM) >= 1.0: score += 3; REASONS.append("rained_now")
            elif float(RAINMM) >= 0.3: score += 1; REASONS.append("drizzle")

            WIND_FMT = format_wind_compact(WDIR_DEG, ANGIN, WINDGUST)
            GUST_FMT = f"{float(WINDGUST):.1f}"
            REASONS_TRIM = []
            for tok in REASONS:
                if not tok: continue
                REASONS_TRIM.append(tok)
                if len(REASONS_TRIM) >= MIN_REASONS_SHOW: break
            REASONS_STR = ",".join(REASONS_TRIM)

            STATUS = "Aman"; COLOR = GREEN; ICON = "✅"
            if score >= 7: STATUS="Rawan"; COLOR=RED; ICON="❌"
            elif score >= 4: STATUS="Waspada"; COLOR=YELLOW; ICON="⚠️"

            if BMK_SUM:
                low = BMK_SUM.lower()
                if re.search(r"hujan sangat|hujan lebat|kilat|petir|badai|thunder|lightning", low):
                    STATUS="Rawan"; COLOR=RED; ICON="❌"
                    AGG_THUNDER[TIME] = AGG_THUNDER.get(TIME,0) + 1
                    PERKOTA_THUNDER[K] = (PERKOTA_THUNDER[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_THUNDER[K] else TIME.replace("T"," ")
                    if "BMKG_warn" not in REASONS: REASONS.append("BMKG_warn")

            if STATUS != "Rawan":
                if float(RAINMM) >= RAWAN_RAIN_MM:
                    STATUS="Rawan"; COLOR=RED; ICON="❌"; REASONS.append("rainmm_rawan")
                elif float(RAINMM) >= WASP_RAIN_MM:
                    STATUS="Waspada"; COLOR=YELLOW; ICON="⚠️"; REASONS.append("rainmm_wasp")
            if STATUS != "Rawan":
                if acc3 >= ACC3_RAWAN_MM or acc6 >= ACC6_RAWAN_MM:
                    STATUS="Waspada"; COLOR=YELLOW; ICON="⚠️"; REASONS.append("acc_rain")
            try:
                if (float(SUHU) >= 33 and float(UV) >= SCORE_UV_TH):
                    PERKOTA_WASP_HEAT[K] = (PERKOTA_WASP_HEAT[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_WASP_HEAT[K] else TIME.replace("T"," ")
                if (float(LEMBAP) >= RAWAN_HUM and float(HUJAN_PROB) >= 30):
                    PERKOTA_WASP_RAIN[K] = (PERKOTA_WASP_RAIN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_WASP_RAIN[K] else TIME.replace("T"," ")
            except:
                pass

            # deviasi flags - prior deterministic
            if dev_mm >= DEV_DANGER_TH:
                PERKOTA_DEV_DANGER[K] = (PERKOTA_DEV_DANGER[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_DEV_DANGER[K] else TIME.replace("T"," ")
                AGG_DEV_DANGER[TIME] = AGG_DEV_DANGER.get(TIME,0) + 1
            elif dev_mm >= DEV_WARN_TH:
                PERKOTA_DEV_WARN[K] = (PERKOTA_DEV_WARN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_DEV_WARN[K] else TIME.replace("T"," ")
                AGG_DEV_WARN[TIME] = AGG_DEV_WARN.get(TIME,0) + 1

            # deviasi flags - ENSEMBLE (ADDED)
            if dev_ens_3hr >= DEV_DANGER_TH:
                # add to PERKOTA_DEV_DANGER (ensemble-driven)
                PERKOTA_DEV_DANGER[K] = (PERKOTA_DEV_DANGER[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_DEV_DANGER[K] else TIME.replace("T"," ")
                AGG_DEV_DANGER[TIME] = AGG_DEV_DANGER.get(TIME,0) + 1
            elif dev_ens_3hr >= DEV_WARN_TH:
                PERKOTA_DEV_WARN[K] = (PERKOTA_DEV_WARN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_DEV_WARN[K] else TIME.replace("T"," ")
                AGG_DEV_WARN[TIME] = AGG_DEV_WARN.get(TIME,0) + 1

            if float(ANGIN) >= WIND_DANGER:
                STATUS="Rawan"; COLOR=RED; ICON="❌"; REASONS.append("wind_sust_danger")
            elif STATUS != "Rawan" and float(ANGIN) >= WIND_WARN:
                STATUS="Waspada"; COLOR=YELLOW; ICON="⚠️"; REASONS.append("wind_warn")
            if float(WINDGUST) >= GUST_DANGER:
                STATUS="Rawan"; COLOR=RED; ICON="❌"; REASONS.append("gust_danger")
            elif STATUS != "Rawan" and float(WINDGUST) >= GUST_WARN:
                STATUS="Waspada"; COLOR=YELLOW; ICON="⚠️"; REASONS.append("gust_warn")

            if float(HUJAN_PROB) >= 70 and float(ANGIN) >= 10:
                AGG_THUNDER[TIME] = AGG_THUNDER.get(TIME,0) + 1
                PERKOTA_THUNDER[K] = (PERKOTA_THUNDER[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_THUNDER[K] else TIME.replace("T"," ")
                if "prob70_wind10" not in REASONS: REASONS.append("prob70_wind10")

            if float(RAINMM) >= WASP_RAIN_MM:
                PERKOTA_WASP_RAIN[K] = (PERKOTA_WASP_RAIN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_WASP_RAIN[K] else TIME.replace("T"," ")
            if acc3 >= ACC3_RAWAN_MM or acc6 >= ACC6_RAWAN_MM:
                PERKOTA_WASP_RAIN[K] = (PERKOTA_WASP_RAIN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_WASP_RAIN[K] else TIME.replace("T"," ")
            if float(WINDGUST) >= GUST_WARN:
                PERKOTA_WASP_GUST[K] = (PERKOTA_WASP_GUST[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_WASP_GUST[K] else TIME.replace("T"," ")

            if STATUS == "Aman":
                AGG_AMAN[TIME] = AGG_AMAN.get(TIME,0) + 1; aman += 1
            if STATUS == "Waspada":
                AGG_WASP[TIME] = AGG_WASP.get(TIME,0) + 1; wasp += 1
            if STATUS == "Rawan":
                AGG_RAWAN[TIME] = AGG_RAWAN.get(TIME,0) + 1; rawan += 1
                PERKOTA_RAWAN[K] = (PERKOTA_RAWAN[K] + " " + TIME.replace("T"," ")).strip() if PERKOTA_RAWAN[K] else TIME.replace("T"," ")

            if float(ANGIN) >= WIND_DANGER: AGG_WIND_DANGER[TIME] = AGG_WIND_DANGER.get(TIME,0) + 1
            if float(ANGIN) >= WIND_WARN: AGG_WIND_WARN[TIME] = AGG_WIND_WARN.get(TIME,0) + 1
            if float(WINDGUST) >= GUST_DANGER: AGG_GUST_DANGER[TIME] = AGG_GUST_DANGER.get(TIME,0) + 1
            if float(WINDGUST) >= GUST_WARN: AGG_GUST_WARN[TIME] = AGG_GUST_WARN.get(TIME,0) + 1

            TGL = TIME.split("T")[0]; JAM = TIME.split("T")[1]
            SUHU_FMT = format_temp_color(SUHU); UV_MARK = format_uv_color(UV)
            is_quiet = False
            if SKIP_QUIET:
                try:
                    if score == 0 and float(RAINMM) < 0.3 and float(HUJAN_PROB) < 10 and float(ANGIN) < WIND_WARN and float(WINDGUST) < GUST_WARN and float(UV) < SCORE_UV_TH and float(LEMBAP) < SCORE_HUMID_TH:
                        is_quiet = True
                except: is_quiet = False

            dev_str = f"{dev_mm:.2f}"
            dev_ens_str = f"{dev_ens_3hr:.2f}"  # ADDED: ensemble dev (3-hr acc stddev)

            if is_quiet:
                if COMPACT:
                    print(f"{TGL} {JAM} | {GREEN}✅ Aman{RESET}")
                else:
                    print("{:<16} | {:<8} | {:<7} | {:<8} | {:<8} | {:<8} | {:<13} | {:<7} | {:<6} | {:<10} | {:<9} | {:<20}".format(
                        f"{TGL} {JAM}", SUHU_FMT, "-", "-", "-", "-", dev_str, WIND_FMT, GUST_FMT, UV_MARK, " ", f"{GREEN}✅ Aman{RESET}", "quiet"))
            else:
                if COMPACT:
                    line = "{:<16} | {:<8} | {:>7}%   | {:>8.1f} | {:>8} | {:<13} | {:>7} | {:<4} | {:<10} | {:<9} | {:<20}".format(
                        f"{TGL} {JAM}", SUHU_FMT, int(HUJAN_PROB), float(RAINMM), int(LEMBAP), dev_str, WIND_FMT, float(GUST_FMT), UV_MARK, SKY_DISPLAY, ICON + " " + STATUS)
                    # append ensemble dev column (added)
                    line = line + f" | DevEns:{dev_ens_str}"
                else:
                    line = "{:<16} | {:<8} | {:>7}%   | {:>8.1f} | {:>8.1f} | {:>8.1f} | {:<8} | {:<8} | {:<13} | {:>7.1f} | {:<6} | {:<10} | {:<9} | {:<20}".format(
                        f"{TGL} {JAM}", SUHU_FMT, int(HUJAN_PROB), float(RAINMM), acc3, acc6, int(LEMBAP), dev_str, WIND_FMT, float(GUST_FMT), UV_MARK, SKY_DISPLAY, ICON + " " + STATUS, REASONS_STR)
                    # append ensemble dev column (added)
                    line = line + f" | DevEns:{dev_ens_str}"
                # For compatibility with existing output, keep color wrapping same
                print(f"{COLOR}{line}{RESET}")
            PREV_TEMP[K] = str(SUHU)
            PREV_TEMP[f"{float(LATK):.4f},{float(LONK):.4f}"] = str(SUHU)

        # ambil sample numeric untuk AI
        try:
            idx_now = None
            if times_jq:
                t_target = TIMES[0][:13]
                for i, tval in enumerate(times_jq):
                    if tval.startswith(t_target):
                        idx_now = i; break
                if idx_now is None:
                    idx_now = 0
            sample = {
                "temp_c": float(temp_arr[idx_now]) if (idx_now is not None and idx_now < len(temp_arr)) else None,
                "hum_pct": float(hum_arr[idx_now]) if (idx_now is not None and idx_now < len(hum_arr)) else None,
                "pop_pct": float(pop_arr[idx_now]) if (idx_now is not None and idx_now < len(pop_arr)) else None,
                "rain_mm": float(prec_arr[idx_now]) if (idx_now is not None and idx_now < len(prec_arr)) else None,
                "wind_dir_deg": float(wdir_arr[idx_now]) if (idx_now is not None and idx_now < len(wdir_arr)) else None,
                "wind_spd_kmh": float(wind_arr[idx_now]) if (idx_now is not None and idx_now < len(wind_arr)) else None,
                "gust_kmh": float(gust_arr[idx_now]) if (idx_now is not None and idx_now < len(gust_arr)) else None,
                "uv_index": float(uv_arr[idx_now]) if (idx_now is not None and idx_now < len(uv_arr)) else None,
                "sky": max(SKY_COUNT[K].items(), key=lambda x: x[1])[0] if SKY_COUNT.get(K) else None,
                "dev_sample_mm": None
            }
            # compute sample dev near current hour for AI summary
            try:
                # ADDED: prefer ensemble-derived dev sample (3-hr accumulated stddev across members), fallback to deterministic window dev
                if ensemble_available and ensemble_members:
                    member_sums_now = []
                    for mem in ensemble_members:
                        s = 0.0
                        for j in (0,1,2):
                            if idx_now + j < len(mem):
                                try:
                                    s += float(mem[idx_now + j] or 0.0)
                                except:
                                    pass
                        member_sums_now.append(s)
                    if len(member_sums_now) >= 2:
                        sample["dev_sample_mm"] = float(statistics.pstdev(member_sums_now))
                    else:
                        # fallback deterministic dev
                        window_vals = []
                        for j in (0,1,2):
                            if idx_now + j < LEN:
                                try: window_vals.append(float(prec_arr[idx_now + j]))
                                except: pass
                        sample["dev_sample_mm"] = float(statistics.pstdev(window_vals)) if len(window_vals) >= 2 else 0.0
                else:
                    window_vals = []
                    for j in (0,1,2):
                        if idx_now + j < LEN:
                            try: window_vals.append(float(prec_arr[idx_now + j]))
                            except: pass
                    sample["dev_sample_mm"] = float(statistics.pstdev(window_vals)) if len(window_vals) >= 2 else 0.0
            except:
                sample["dev_sample_mm"] = None
            PER_LOC_SAMPLE[K] = sample
        except Exception:
            PER_LOC_SAMPLE[K] = {
                "temp_c": None, "hum_pct": None, "pop_pct": None, "rain_mm": None,
                "wind_dir_deg": None, "wind_spd_kmh": None, "gust_kmh": None, "uv_index": None, "sky": None, "dev_sample_mm": None
            }

        # ringkasan per lokasi
        print()
        print(f"{CYAN}Ringkasan untuk {K}:{RESET}")
        print(f"✅ Aman: {aman} jam | ⚠️ Waspada: {wasp} jam | ❌ Rawan: {rawan} jam")
        if PERKOTA_THUNDER.get(K): print(f"{RED}⚡ Potensi badai/petir di {K}:{RESET} {PERKOTA_THUNDER[K]}")
        print()
        def tidy(s:str)->str:
            return " ".join(s.split()) if s else ""
        WASP_RAIN = tidy(PERKOTA_WASP_RAIN[K]); WASP_HEAT = tidy(PERKOTA_WASP_HEAT[K]); WASP_GUST = tidy(PERKOTA_WASP_GUST[K])
        THUNDER = tidy(PERKOTA_THUNDER[K]); RAWAN_LIST = tidy(PERKOTA_RAWAN[K]); REALR_RAW = tidy(PERKOTA_REALRAIN[K])
        DEV_WARN_LIST = tidy(PERKOTA_DEV_WARN[K]); DEV_DANGER_LIST = tidy(PERKOTA_DEV_DANGER[K])
        if REALR_RAW:
            real_lines = sorted(set([l.strip() for l in REALR_RAW.splitlines() if l.strip()]))
            REAL_COUNT = len(real_lines); REAL_PRETTY = []
            for item in real_lines:
                cat = item.split(":")[-1]; timepart = ":".join(item.split(":")[:-1])
                cat_lc = cat.lower(); cat_f = cat_lc
                if "gerimis" in cat_lc: cat_f = "gerimis"
                elif "ringan" in cat_lc: cat_f = "ringan"
                elif "sedang" in cat_lc and "hujan" in cat_lc:
                    cat_f = "sedang"
                elif "deras" in cat_lc or "keras" in cat_lc: cat_f = "deras"
                REAL_PRETTY.append(f"{timepart} ({cat_f})")
            if REAL_COUNT == 1: REAL_LABEL = "Rendah"; REAL_COLOR = YELLOW
            elif REAL_COUNT <= 3: REAL_LABEL = "Sedang"; REAL_COLOR = YELLOW
            else: REAL_LABEL = "Tinggi"; REAL_COLOR = RED
            REAL_PRETTY_S = ", ".join(REAL_PRETTY)
        else:
            REAL_PRETTY_S = ""; REAL_COUNT = 0; REAL_LABEL = "Tidak terdeteksi"; REAL_COLOR = GREEN

        print(f"{BOLD}Ringkasan spesifik {K}:{RESET}")
        print(f"  ⚠️ Waspada hujan/akumulasi: {YELLOW}{WASP_RAIN if WASP_RAIN else 'Tidak terdeteksi'}{RESET}")
        print(f"  ⚠️ Waspada panas/UV: {YELLOW}{WASP_HEAT if WASP_HEAT else 'Tidak terdeteksi'}{RESET}")
        print(f"  ⚠️ Waspada gust: {YELLOW}{WASP_GUST if WASP_GUST else 'Tidak terdeteksi'}{RESET}")
        print(f"  ⚡ Potensi badai/petir: {RED}{THUNDER if THUNDER else 'Tidak terdeteksi'}{RESET}")
        print(f"  ❌ Jam berstatus Rawan: {RED}{RAWAN_LIST if RAWAN_LIST else 'Tidak terdeteksi'}{RESET}")
        if DEV_WARN_LIST or DEV_DANGER_LIST:
            dev_info = (f"Warn: {DEV_WARN_LIST} " if DEV_WARN_LIST else "") + (f"Danger: {DEV_DANGER_LIST}" if DEV_DANGER_LIST else "")
            print(f"  ℹ️ Jam deviasi tinggi: {YELLOW}{dev_info}{RESET}")
        else:
            print(f"  ℹ️ Jam deviasi tinggi: Tidak terdeteksi")
        if REAL_COUNT > 0:
            print(f"  ❗ Risiko hujan nyata: {REAL_COLOR}{REAL_LABEL}{RESET} — {REAL_COUNT} jam: {REAL_PRETTY_S}")
        else:
            print(f"  ❗ Risiko hujan nyata: {GREEN}Tidak terdeteksi{RESET}")
        print()

        RG = tidy(PERKOTA_RAIN_GERIMIS[K]); RR = tidy(PERKOTA_RAIN_RINGAN[K]); RS = tidy(PERKOTA_RAIN_SEDANG[K]); RD = tidy(PERKOTA_RAIN_DERAS[K])
        print(f"{BOLD}Ringkasan hujan per kategori {K}:{RESET}")
        print(f"  ☂️ Gerimis: {GREEN}{RG if RG else 'Tidak terdeteksi'}{RESET}")
        print(f"  ☂️ Ringan: {YELLOW}{RR if RR else 'Tidak terdeteksi'}{RESET}")
        print(f"  ☂️ Sedang: {YELLOW}{RS if RS else 'Tidak terdeteksi'}{RESET}")
        print(f"  ☂️ Deras: {RED}{RD if RD else 'Tidak terdeteksi'}{RESET}")
        print()
        print(f"{BOLD}Ringkasan langit {K}:{RESET}")
        skcnt = SKY_COUNT[K]
        if not skcnt: print("  Tidak tersedia")
        else:
            for key, val in skcnt.items(): print(f"  - {key}: {val} jam")
        print()

    try:
        save_prev_temp_file(PREV_TEMP)
    except:
        pass

    # gabungan summary
    print(f"{BOLD}{CYAN}=== Ringkasan Gabungan (24 jam) ==={RESET}")
    print("Waktu                | #Aman | #Waspada | #Rawan | #Potensi_Badai | #Angin15+ | #Angin25+ | #Gust30+ | #Gust45+ | #DevWarn | #DevDanger | Ger | Rng | Sdg | Drs | Catatan")
    print("-"*130)
    best_aman_times = []; best_thunder_times = []; any_rawan_times = []
    wind_warn_times = []; wind_danger_times = []; gust_warn_times = []; gust_danger_times = []; dev_warn_times = []; dev_danger_times = []

    for t in TIMES:
        a = AGG_AMAN.get(t,0); w = AGG_WASP.get(t,0); r = AGG_RAWAN.get(t,0); th = AGG_THUNDER.get(t,0)
        aw = AGG_WIND_WARN.get(t,0); ad = AGG_WIND_DANGER.get(t,0)
        gw = AGG_GUST_WARN.get(t,0); gd = AGG_GUST_DANGER.get(t,0)
        d_warn = AGG_DEV_WARN.get(t,0); d_danger = AGG_DEV_DANGER.get(t,0)
        ger = AGG_RAIN_GERIMIS.get(t,0); rn = AGG_RAIN_RINGAN.get(t,0); sd = AGG_RAIN_SEDANG.get(t,0); dr = AGG_RAIN_DERAS.get(t,0)
        note = ""
        if th > 0: note = f"Potensi badai/petir di {th} lokasi"
        if r > 0: note = f"Risiko hujan di {r} lokasi"
        TGL = t.split("T")[0]; JAM = t.split("T")[1]
        print(f"{TGL} {JAM} | {a:5d} | {w:8d} | {r:6d} | {th:14d} | {aw:9d} | {ad:9d} | {gw:8d} | {gd:8d} | {d_warn:7d} | {d_danger:10d} | {ger:3d} | {rn:3d} | {sd:3d} | {dr:3d} | {note}")
        if processed_count > 0 and a >= int(processed_count * THRESH_PCT + 0.999):
            best_aman_times.append(t)
        if th > 0: best_thunder_times.append(t)
        if r > 1: any_rawan_times.append(t)
        if aw > 0: wind_warn_times.append(t)
        if ad > 0: wind_danger_times.append(t)
        if gw > 0: gust_warn_times.append(t)
        if gd > 0: gust_danger_times.append(t)
        if d_warn > 0: dev_warn_times.append(t)
        if d_danger > 0: dev_danger_times.append(t)

    def fmt_list(arr):
        return ", ".join([x.replace("T"," ") for x in arr]) if arr else "Tidak ada"

    print(f"\n{BOLD}Rekomendasi gabungan:{RESET}")
    if best_aman_times:
        print(f"Jam paling AMAN ({processed_count} lokasi, ambang {int(THRESH_PCT*100)}%): {GREEN}{fmt_list(best_aman_times)}{RESET}")
    else:
        print(f"Jam paling AMAN: {YELLOW}Tidak ada{RESET}")
    if any_rawan_times:
        print(f"Jam dengan risiko hujan (>=2 lokasi): {RED}{fmt_list(any_rawan_times)}{RESET}")
    else:
        print(f"Jam dengan risiko hujan: {GREEN}Tidak terdeteksi{RESET}")
    if best_thunder_times:
        print(f"Jam dengan POTENSI BADAi/PETIR: {RED}{fmt_list(best_thunder_times)}{RESET}")
    else:
        print(f"Jam dengan POTENSI BADAi/PETIR: {YELLOW}Tidak terdeteksi{RESET}")

    # deviasi summary
    if dev_warn_times or dev_danger_times:
        print(f"Jam dengan deviasi tinggi: {YELLOW}{fmt_list(dev_warn_times)} (waspada){RESET}, {RED}{fmt_list(dev_danger_times)} (danger){RESET}")
    else:
        print(f"Jam dengan deviasi tinggi: {GREEN}Tidak terdeteksi{RESET}")

    print(f"\n{BOLD}Potensi badai/petir per lokasi:{RESET}")
    for K in processed_locations_list:
        val = PERKOTA_THUNDER.get(K,""); print(f"- {K}: {val if val else 'Tidak terdeteksi'}")
    print()
    print(f"{BOLD}Ringkasan hujan gabungan (jumlah lokasi per jam):{RESET}")
    for t in TIMES:
        print(f"{t.replace('T',' ')} | Ger:{AGG_RAIN_GERIMIS.get(t,0)} Rn:{AGG_RAIN_RINGAN.get(t,0)} Sd:{AGG_RAIN_SEDANG.get(t,0)} Dr:{AGG_RAIN_DERAS.get(t,0)}")
    print()
    print(f"{CYAN}Catatan: BMKG auto-detect dari {BMKG_INDEX_URL}. Heuristik petir aktif (prob≥70%, angin≥10). Deviasi dihitung sebagai std dev (3-jam window) curah hujan (mm). Ensemble deviasi (DevEns) dihitung dari std dev akumulasi 3-jam antar anggota ensemble (jika tersedia).{RESET}")

    # prepare per-loc structured for AI
    per_loc_struct = {}
    for K in processed_locations_list:
        samp = PER_LOC_SAMPLE.get(K, {})
        temp_val = samp.get("temp_c") if samp else None
        hum_val = samp.get("hum_pct") if samp else None
        pop_val = samp.get("pop_pct") if samp else None
        rain_val = samp.get("rain_mm") if samp else None
        wind_dir = samp.get("wind_dir_deg") if samp else None
        wind_spd = samp.get("wind_spd_kmh") if samp else None
        gust_v = samp.get("gust_kmh") if samp else None
        uv_v = samp.get("uv_index") if samp else None
        sky_label = samp.get("sky") if samp else None
        dev_sample = samp.get("dev_sample_mm") if samp else None

        thunder_times = PERKOTA_THUNDER.get(K,"").split() if PERKOTA_THUNDER.get(K,"") else []
        realrain_events = [l.strip() for l in (PERKOTA_REALRAIN.get(K,"") or "").splitlines() if l.strip()]
        wasp_rain_times = PERKOTA_WASP_RAIN.get(K,"").split() if PERKOTA_WASP_RAIN.get(K,"") else []
        wasp_heat_times = PERKOTA_WASP_HEAT.get(K,"").split() if PERKOTA_WASP_HEAT.get(K,"") else []
        wasp_gust_times = PERKOTA_WASP_GUST.get(K,"").split() if PERKOTA_WASP_GUST.get(K,"") else []
        rawan_times = PERKOTA_RAWAN.get(K,"").split() if PERKOTA_RAWAN.get(K,"") else []
        dev_warn_times = PERKOTA_DEV_WARN.get(K,"").split() if PERKOTA_DEV_WARN.get(K,"") else []
        dev_danger_times = PERKOTA_DEV_DANGER.get(K,"").split() if PERKOTA_DEV_DANGER.get(K,"") else []
        dev_times = (dev_warn_times or []) + (dev_danger_times or [])

        per_loc_struct[K] = {
            "temp_sample_c": temp_val,
            "hum_pct": hum_val,
            "pop_pct": pop_val,
            "rain_mm": rain_val,
            "wind_dir_deg": wind_dir,
            "wind_spd_kmh": wind_spd,
            "gust_kmh": gust_v,
            "uv_index": uv_v,
            "sky_label": sky_label,
            "sky_summary": SKY_COUNT.get(K, {}),
            "thunder_times": thunder_times,
            "realrain_events": realrain_events,
            "wasp_rain_times": wasp_rain_times,
            "wasp_heat_times": wasp_heat_times,
            "wasp_gust_times": wasp_gust_times,
            "rawan_times": rawan_times,
            "dev_times": dev_times,
            "dev_sample_mm": dev_sample,
            "hours_aman_count": sum(1 for t in TIMES if t in best_aman_times),
            "hours_rawan_count": sum(1 for t in TIMES if t in any_rawan_times),
        }

    # AI summarizer call
    try:
        ai_text = ai_summarize_weather_structured(per_loc_struct, best_aman_times, any_rawan_times, TIMESTAMP_NOW)
    except Exception:
        ai_text = ""

    if ai_text:
        telegram_text = ai_text
    else:
        lines = []
        for K in processed_locations_list:
            status_short = "Aman"
            if PERKOTA_RAWAN.get(K): status_short = "Rawan"
            elif PERKOTA_WASP_RAIN.get(K) or PERKOTA_WASP_HEAT.get(K) or PERKOTA_WASP_GUST.get(K) or PERKOTA_DEV_WARN.get(K) or PERKOTA_DEV_DANGER.get(K):
                status_short = "Waspada"
            tmp = PREV_TEMP.get(K) or PREV_TEMP.get(f"{DEFAULT_LAT.get(K,0):.4f},{DEFAULT_LON.get(K,0):.4f}", "")
            tmp_str = f"{float(tmp):.0f}°C" if tmp else "-"
            rain_hint = "hujan: terdeteksi" if PERKOTA_REALRAIN.get(K) else "hujan: kecil"
            dev_hint = ""
            if PERKOTA_DEV_DANGER.get(K):
                dev_hint = " | DEV:DANGER"
            elif PERKOTA_DEV_WARN.get(K):
                dev_hint = " | DEV:WARN"
            line = f"☁️ {K}: {tmp_str}, {status_short}, {rain_hint}{dev_hint}"
            lines.append(line)
        def join_ranges(arr):
            if not arr: return "-"
            hrs = sorted({t.split("T")[1][:2] for t in arr})
            runs = []
            start = prev = int(hrs[0])
            for s in map(int, hrs[1:]):
                if s == prev + 1:
                    prev = s
                    continue
                if start == prev:
                    runs.append(f"{start:02d}:00")
                else:
                    runs.append(f"{start:02d}:00-{prev:02d}:00")
                start = prev = s
            if start == prev:
                runs.append(f"{start:02d}:00")
            else:
                runs.append(f"{start:02d}:00-{prev:02d}:00")
            return ", ".join(runs)
        jam_aman = _join_hours_to_ranges(best_aman_times) if '_join_hours_to_ranges' in globals() else join_ranges(best_aman_times)
        jam_risiko = _join_hours_to_ranges(any_rawan_times) if '_join_hours_to_ranges' in globals() else join_ranges(any_rawan_times)
        telegram_text = "\n".join(lines) + "\n\nJam paling aman narik: " + jam_aman + "\nJam berisiko: " + jam_risiko

    # ------------------ TAMBAHAN: Kesimpulan tegas (AI-first, fallback lokal) ------------------
    try:
        kesimpulan_tegas = generate_conclusion(per_loc_struct, processed_locations_list, best_aman_times, any_rawan_times, TIMESTAMP_NOW)
        telegram_text = telegram_text + "\n\n" + kesimpulan_tegas
    except Exception as e:
        log("Error membuat kesimpulan tegas: " + str(e))
        telegram_text = telegram_text + "\n\nKesimpulan tegasnya: Tidak dapat dibuat saat ini."

    # -----------------------------------------------------------------------------------------------

    # append update timestamp
    telegram_text = telegram_text + f"\nUpdate: {TIMESTAMP_NOW}"

    if len(telegram_text) > 3490:
        telegram_text = telegram_text[:3490] + "\n\n[truncated]"

    if not OPENAI_API_KEY:
        log("OPENAI_API_KEY kosong — telegram tidak dikirim. Set OPENAI_API_KEY untuk mengaktifkan pengiriman.")
    else:
        send_telegram(telegram_text)

# ---------- run mode ----------

def main_loop():
    if MODE == "daemon":
        log(f"Menjalankan dalam mode daemon. Interval: {REFRESH_INTERVAL} detik.")
        while True:
            run_once()
            log(f"Menunggu {REFRESH_INTERVAL} detik sebelum refresh...")
            time.sleep(REFRESH_INTERVAL)
    else:
        run_once()

# ---------- helper kecil lagi ----------

def _join_hours_to_ranges(hours_list: List[str]) -> str:
    if not hours_list: return "-"
    hrs = sorted(list({h.split("T")[1][:2] for h in hours_list}))
    hrs_int = sorted([int(h) for h in hrs])
    ranges = []
    start = prev = hrs_int[0]
    for h in hrs_int[1:]:
        if h == prev + 1:
            prev = h
            continue
        if start == prev:
            ranges.append(f"{start:02d}:00")
        else:
            ranges.append(f"{start:02d}:00-{prev:02d}:00")
        start = prev = h
    if start == prev:
        ranges.append(f"{start:02d}:00")
    else:
        ranges.append(f"{start:02d}:00-{prev:02d}:00")
    return ", ".join(ranges)

if __name__ == "__main__":
    main_loop()
