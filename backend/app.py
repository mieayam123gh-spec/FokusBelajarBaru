"""FokusBelajar backend - server Python (Flask) untuk kontrol orang tua.

Jalankan di Termux:
    FOKUS_TOKEN=tokenrahasia python app.py

Endpoint utama:
    GET  /                  -> dashboard web monitoring (buka di browser HP ortu)
    GET  /api/health        -> cek server hidup
    GET  /api/rules         -> ambil aturan (aplikasi diblokir + status sesi)
    POST /api/rules         -> simpan aturan
    POST /api/session/start -> mulai sesi belajar
    POST /api/session/stop  -> akhiri sesi belajar
    GET  /api/sessions      -> rekap sesi hari ini
    POST /api/activity      -> HP anak lapor "sedang buka aplikasi X"
    GET  /api/live          -> status live: aplikasi yang sedang dibuka tiap device
    GET  /api/activity      -> riwayat aplikasi yang dibuka anak
"""

import json
import os
import sqlite3
import time
from functools import wraps

from flask import Flask, jsonify, request, Response

TOKEN = os.environ.get("FOKUS_TOKEN", "ganti-token-ini")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fokus.db")
LIVE_WINDOW = 45  # detik: event lebih baru dari ini dianggap "sedang dibuka"

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device TEXT NOT NULL,
            package TEXT NOT NULL,
            ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity (ts);
        INSERT OR IGNORE INTO settings (key, value) VALUES ('blocked', '[]');
    """)
    conn.commit()
    conn.close()


def get_setting(conn, key, default):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def open_session(conn):
    return conn.execute(
        "SELECT id, started_at FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()


def require_token(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Token") != TOKEN:
            return jsonify(error="token salah"), 401
        return fn(*args, **kwargs)
    return wrapper


@app.get("/api/health")
def health():
    return jsonify(ok=True, service="FokusBelajar", time=int(time.time()))


@app.get("/api/rules")
@require_token
def get_rules():
    conn = get_db()
    blocked = json.loads(get_setting(conn, "blocked", "[]"))
    active = open_session(conn) is not None
    conn.close()
    return jsonify(blocked=blocked, session_active=active)


@app.post("/api/rules")
@require_token
def set_rules():
    data = request.get_json(silent=True) or {}
    blocked = data.get("blocked")
    if not isinstance(blocked, list) or not all(isinstance(x, str) for x in blocked):
        return jsonify(error="blocked harus berupa daftar teks"), 400
    conn = get_db()
    set_setting(conn, "blocked", json.dumps(blocked))
    conn.commit()
    conn.close()
    return jsonify(ok=True, blocked=blocked)


@app.post("/api/session/start")
@require_token
def start_session():
    conn = get_db()
    if open_session(conn) is not None:
        conn.close()
        return jsonify(ok=True, message="sesi sudah berjalan")
    conn.execute("INSERT INTO sessions (started_at) VALUES (?)", (int(time.time()),))
    conn.commit()
    conn.close()
    return jsonify(ok=True, message="sesi dimulai")


@app.post("/api/session/stop")
@require_token
def stop_session():
    conn = get_db()
    s = open_session(conn)
    if s is not None:
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (int(time.time()), s["id"]))
        conn.commit()
    conn.close()
    return jsonify(ok=True)


@app.get("/api/sessions")
@require_token
def sessions():
    now = int(time.time())
    t = time.localtime(now)
    day_start = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    conn = get_db()
    rows = conn.execute(
        "SELECT started_at, COALESCE(ended_at, ?) AS ended FROM sessions WHERE started_at >= ?",
        (now, day_start),
    ).fetchall()
    conn.close()
    total_seconds = sum(r["ended"] - r["started_at"] for r in rows)
    return jsonify(today_sessions=len(rows), today_minutes=total_seconds // 60)


# ---------------------------------------------------------------- live screen

@app.post("/api/activity")
@require_token
def report_activity():
    """HP anak melapor: aplikasi apa yang sedang dibuka.

    Body boleh satu event atau batch:
        {"device": "HP Anak", "package": "com.youtube"}
        {"device": "HP Anak", "events": [{"package": "...", "ts": 123}]}
    """
    data = request.get_json(silent=True) or {}
    device = data.get("device")
    if not isinstance(device, str) or not device.strip():
        return jsonify(error="device wajib diisi"), 400
    device = device.strip()[:60]
    now = int(time.time())

    events = data.get("events")
    if events is None:
        pkg = data.get("package") or data.get("app")
        if not isinstance(pkg, str) or not pkg.strip():
            return jsonify(error="package wajib diisi"), 400
        events = [{"package": pkg, "ts": data.get("ts") or now}]

    if not isinstance(events, list) or len(events) > 200:
        return jsonify(error="events tidak valid"), 400

    rows = []
    for e in events:
        pkg = e.get("package") or e.get("app")
        ts = e.get("ts")
        if not isinstance(pkg, str) or not pkg.strip():
            continue
        if not isinstance(ts, int) or ts <= 0 or ts > now + 300:
            ts = now
        rows.append((device, pkg.strip()[:200], ts))

    if not rows:
        return jsonify(error="tidak ada event valid"), 400

    conn = get_db()
    conn.executemany(
        "INSERT INTO activity (device, package, ts) VALUES (?, ?, ?)", rows
    )
    # bersihkan riwayat lebih dari 7 hari, sekali-sekali
    if (rows[-1][2] // 3600) % 50 == 0:
        conn.execute("DELETE FROM activity WHERE ts < ?", (now - 7 * 24 * 3600,))
    conn.commit()
    conn.close()
    return jsonify(ok=True, saved=len(rows))


@app.get("/api/live")
@require_token
def live():
    """Status live: aplikasi yang SEDANG dibuka tiap device + 30 kejadian terakhir."""
    now = int(time.time())
    conn = get_db()

    latest = conn.execute(
        "SELECT device, package, MAX(ts) AS ts FROM activity GROUP BY device"
    ).fetchall()
    devices = []
    for r in latest:
        age = now - r["ts"]
        devices.append({
            "device": r["device"],
            "current_app": r["package"] if age <= LIVE_WINDOW else None,
            "last_app": r["package"],
            "updated_at": r["ts"],
            "seconds_ago": age,
            "live": age <= LIVE_WINDOW,
        })

    recent = conn.execute(
        "SELECT device, package, ts FROM activity ORDER BY ts DESC, id DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return jsonify(
        now=now,
        session_active=False,
        devices=devices,
        recent=[dict(r) for r in recent],
    )


@app.get("/api/activity")
@require_token
def activity_history():
    """Riwayat aplikasi yang dibuka anak. Query: ?limit=100&device=..."""
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))
    device = request.args.get("device")

    conn = get_db()
    if device:
        rows = conn.execute(
            "SELECT device, package, ts FROM activity WHERE device = ? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (device, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT device, package, ts FROM activity ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return jsonify(activity=[dict(r) for r in rows])


# ---------------------------------------------------------------- dashboard

DASHBOARD_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FokusBelajar - Pantauan Live</title>
<style>
  body { font-family: sans-serif; background: #0f172a; color: #e2e8f0;
         margin: 0; padding: 16px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #94a3b8; font-size: 13px; margin-bottom: 16px; }
  .card { background: #1e293b; border-radius: 12px; padding: 16px;
          margin-bottom: 16px; }
  .card h2 { font-size: 15px; margin: 0 0 8px; color: #7dd3fc; }
  input, button { font-size: 15px; border-radius: 8px; padding: 10px;
                  border: 1px solid #334155; background: #0f172a;
                  color: #e2e8f0; }
  button { background: #2563eb; border: none; font-weight: bold; }
  .now { font-size: 17px; font-weight: bold; word-break: break-all; }
  .off { color: #f87171; }
  .on  { color: #4ade80; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
         margin-right: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  td, th { padding: 6px 4px; text-align: left; border-bottom: 1px solid #334155; }
  th { color: #94a3b8; }
  .err { color: #f87171; font-size: 13px; }
</style>
</head>
<body>
<h1>FokusBelajar - Pantauan Live</h1>
<div class="sub">Lihat aplikasi apa yang sedang dibuka anak, diperbarui tiap 3 detik.</div>

<div class="card">
  <h2>Token server</h2>
  <input id="token" type="password" placeholder="FOKUS_TOKEN">
  <button onclick="saveToken()">Simpan</button>
  <div id="authErr" class="err"></div>
</div>

<div id="liveBox" class="card">
  <h2>Sedang dibuka sekarang</h2>
  <div id="liveNow" class="now">-</div>
</div>

<div class="card">
  <h2>30 aplikasi terakhir yang dibuka</h2>
  <table>
    <tr><th>Waktu</th><th>Device</th><th>Aplikasi</th></tr>
    <tbody id="recentBody"><tr><td colspan="3">-</td></tr></tbody>
  </table>
</div>

<script>
const KEY = 'fokus_token';
const tokenEl = document.getElementById('token');
tokenEl.value = localStorage.getItem(KEY) || '';

function saveToken() {
  localStorage.setItem(KEY, tokenEl.value.trim());
  refresh();
}

function fmt(ts) {
  return new Date(ts * 1000).toLocaleTimeString('id-ID');
}

async function refresh() {
  const token = localStorage.getItem(KEY) || '';
  if (!token) { document.getElementById('authErr').textContent = 'Isi token dulu.'; return; }
  try {
    const r = await fetch('/api/live', { headers: { 'X-Token': token } });
    if (r.status === 401) {
      document.getElementById('authErr').textContent = 'Token salah.';
      return;
    }
    document.getElementById('authErr').textContent = '';
    const j = await r.json();
    const liveNow = document.getElementById('liveNow');
    const dev = j.devices && j.devices[0];
    if (dev && dev.live && dev.current_app) {
      liveNow.innerHTML = '<span class="dot on"></span>' + dev.current_app +
        ' <small>(update ' + dev.seconds_ago + ' dtk lalu)</small>';
    } else if (dev) {
      liveNow.innerHTML = '<span class="dot off"></span>Tidak ada laporan baru (' +
        Math.round(dev.seconds_ago / 60) + ' mnt lalu: ' + (dev.last_app || '-') + ')';
    } else {
      liveNow.innerHTML = '<span class="dot off"></span>Belum ada data dari HP anak.';
    }
    const tb = document.getElementById('recentBody');
    tb.innerHTML = (j.recent || []).map(e =>
      '<tr><td>' + fmt(e.ts) + '</td><td>' + e.device + '</td><td>' + e.package + '</td></tr>'
    ).join('') || '<tr><td colspan="3">Belum ada data.</td></tr>';
  } catch (e) {
    document.getElementById('authErr').textContent = 'Gagal terhubung: ' + e.message;
  }
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


@app.get("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html")


@app.errorhandler(Exception)
def on_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    app.logger.exception("kesalahan tak terduga")
    return jsonify(error="kesalahan server internal"), 500


if __name__ == "__main__":
    init_db()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"FokusBelajar server jalan di http://{host}:{port}")
    app.run(host=host, port=port, threaded=True)
