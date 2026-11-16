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
    session_active = open_session(conn) is not None
    conn.close()
    return jsonify(
        now=now,
        session_active=session_active,
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
<title>FokusBelajar - Panel Orang Tua</title>
<style>
  body { font-family: sans-serif; background: #0f172a; color: #e2e8f0;
         margin: 0; padding: 16px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #94a3b8; font-size: 13px; margin-bottom: 16px; }
  .card { background: #1e293b; border-radius: 12px; padding: 16px;
          margin-bottom: 16px; }
  .card h2 { font-size: 15px; margin: 0 0 8px; color: #7dd3fc; }
  input, textarea, button { font-size: 15px; border-radius: 8px;
                  padding: 10px; border: 1px solid #334155;
                  background: #0f172a; color: #e2e8f0; }
  textarea { width: 100%; box-sizing: border-box; font-size: 14px; }
  button { background: #2563eb; border: none; font-weight: bold;
           margin: 4px 4px 0 0; }
  button.stop { background: #dc2626; }
  button.gray { background: #334155; }
  .badge { display: inline-block; padding: 4px 10px; border-radius: 999px;
           font-size: 13px; font-weight: bold; }
  .badge.on  { background: #14532d; color: #4ade80; }
  .badge.off { background: #3f1d1d; color: #f87171; }
  .now { font-size: 17px; font-weight: bold; word-break: break-all; }
  .dot { display: inline-block; width: 10px; height: 10px;
         border-radius: 50%; margin-right: 6px; }
  .on  { color: #4ade80; }
  .off { color: #f87171; }
  .err { color: #f87171; font-size: 13px; }
  .ok  { color: #4ade80; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  td, th { padding: 6px 4px; text-align: left;
           border-bottom: 1px solid #334155; }
  th { color: #94a3b8; }
  .stats { font-size: 15px; }
  .stats b { color: #7dd3fc; }
</style>
</head>
<body>
<h1>FokusBelajar - Panel Orang Tua</h1>
<div class="sub">Semua kontrol dari browser. Data live diperbarui tiap 3 detik.</div>

<div class="card">
  <h2>1. Token server</h2>
  <input id="token" type="password" placeholder="FOKUS_TOKEN" size="20">
  <button onclick="saveToken()">Simpan</button>
  <div id="authMsg" class="err"></div>
</div>

<div class="card">
  <h2>2. Status sesi belajar</h2>
  <div><span id="sesBadge" class="badge off">memuat...</span>
       <span id="sesInfo" style="color:#94a3b8;font-size:13px"></span></div>
  <button onclick="sesStart()">Mulai sesi</button>
  <button class="stop" onclick="sesStop()">Berhenti sesi</button>
</div>

<div class="card">
  <h2>3. Aplikasi yang diblokir saat sesi</h2>
  <textarea id="blocked" rows="3"
    placeholder="com.google.android.youtube, com.mobile.legends"></textarea>
  <button onclick="saveRules()">Simpan daftar blokir</button>
  <div id="rulesMsg"></div>
</div>

<div class="card">
  <h2>4. Live Screen - sedang dibuka sekarang</h2>
  <div id="liveNow" class="now"><span class="dot off"></span>-</div>
  <div id="liveInfo" style="color:#94a3b8;font-size:13px"></div>
</div>

<div class="card">
  <h2>5. Riwayat aplikasi yang dibuka anak</h2>
  <table>
    <tr><th>Waktu</th><th>Device</th><th>Aplikasi</th></tr>
    <tbody id="recentBody"><tr><td colspan="3">-</td></tr></tbody>
  </table>
</div>

<div class="card">
  <h2>6. Rekap belajar hari ini</h2>
  <div id="statsBox" class="stats">-</div>
</div>

<script>
const KEY = 'fokus_token';
const tokenEl = document.getElementById('token');
tokenEl.value = localStorage.getItem(KEY) || '';

function saveToken() {
  localStorage.setItem(KEY, tokenEl.value.trim());
  refresh(true);
}

function fmt(ts) {
  return new Date(ts * 1000).toLocaleTimeString('id-ID');
}

async function api(path, opts) {
  const token = localStorage.getItem(KEY) || '';
  const r = await fetch(path, Object.assign({}, opts || {},
    { headers: Object.assign({ 'X-Token': token }, (opts && opts.headers) || {}) }));
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) {
    document.getElementById('authMsg').textContent =
      'Token salah atau belum diisi.';
    throw new Error('unauthorized');
  }
  return { status: r.status, body: j };
}

async function sesStart() {
  try {
    await api('/api/session/start', { method: 'POST' });
    refresh(true);
  } catch (e) {}
}

async function sesStop() {
  try {
    await api('/api/session/stop', { method: 'POST' });
    refresh(true);
  } catch (e) {}
}

async function saveRules() {
  const msg = document.getElementById('rulesMsg');
  const list = document.getElementById('blocked').value
    .split(',').map(s => s.trim()).filter(s => s.length > 0);
  try {
    const r = await api('/api/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocked: list })
    });
    if (r.status === 400) {
      msg.className = 'err'; msg.textContent = 'Format daftar tidak valid.';
      return;
    }
    msg.className = 'ok';
    msg.textContent = 'Daftar blokir tersimpan (' + list.length + ' aplikasi).';
  } catch (e) {
    msg.className = 'err'; msg.textContent = 'Gagal: ' + e.message;
  }
}

async function refresh(force) {
  const token = localStorage.getItem(KEY) || '';
  if (!token) {
    document.getElementById('authMsg').textContent = 'Isi token dulu.';
    return;
  }
  try {
    document.getElementById('authMsg').textContent = '';

    const rules = await api('/api/rules');
    const badge = document.getElementById('sesBadge');
    if (rules.body.session_active) {
      badge.className = 'badge on'; badge.textContent = 'Sesi AKTIF';
      document.getElementById('sesInfo').textContent =
        'anak sedang dalam sesi belajar';
    } else {
      badge.className = 'badge off'; badge.textContent = 'Sesi tidak berjalan';
      document.getElementById('sesInfo').textContent =
        'tekan "Mulai sesi" di sini, lalu anak tinggal buka aplikasinya';
    }
    if (!document.getElementById('blocked').dataset.dirty) {
      document.getElementById('blocked').value =
        (rules.body.blocked || []).join(', ');
    }

    const live = await api('/api/live');
    const liveNow = document.getElementById('liveNow');
    const liveInfo = document.getElementById('liveInfo');
    const dev = (live.body.devices || [])[0];
    if (dev && dev.live && dev.current_app) {
      liveNow.innerHTML = '<span class="dot on"></span>' + dev.current_app;
      liveInfo.textContent = 'update ' + dev.seconds_ago + ' dtk lalu';
    } else if (dev) {
      liveNow.innerHTML = '<span class="dot off"></span>Tidak ada laporan baru';
      liveInfo.textContent = 'laporan terakhir ' +
        Math.round(dev.seconds_ago / 60) + ' mnt lalu: ' + (dev.last_app || '-');
    } else {
      liveNow.innerHTML = '<span class="dot off"></span>Belum ada data dari HP anak';
      liveInfo.textContent = 'pastikan APK sudah terpasang & sesi berjalan di HP anak';
    }
    const tb = document.getElementById('recentBody');
    tb.innerHTML = (live.body.recent || []).map(e =>
      '<tr><td>' + fmt(e.ts) + '</td><td>' + e.device + '</td><td>' +
      e.package + '</td></tr>'
    ).join('') || '<tr><td colspan="3">Belum ada data.</td></tr>';

    const st = await api('/api/sessions');
    document.getElementById('statsBox').innerHTML =
      '<b>' + st.body.today_sessions + '</b> sesi hari ini, total <b>' +
      st.body.today_minutes + '</b> menit.';
  } catch (e) {}
}

// tandai textarea agar tidak ditimpa ulang saat pengguna sedang mengetik
document.getElementById('blocked').addEventListener('input', function () {
  this.dataset.dirty = '1';
});
document.getElementById('blocked').addEventListener('change', function () {
  this.dataset.dirty = '';
});

refresh(true);
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
