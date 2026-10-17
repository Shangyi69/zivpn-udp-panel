#!/usr/bin/env python3
"""zvpn-panel: web panel for ZIVPN multi-user (login + user management).

Uses only the Python standard library. Reuses the functions in zvpn.py.

  python3 panel.py set-admin <username> <password>   create/replace the admin login
  python3 panel.py serve                             run the web panel
"""
import hashlib, hmac, html, json, os, secrets, sys, time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import zvpn

PANEL_DB = os.path.join(zvpn.HOME, "panel.json")
PORT = int(os.environ.get("ZVPN_PANEL_PORT", "8088"))
BIND = os.environ.get("ZVPN_PANEL_BIND", "0.0.0.0")
SESSION_TTL = 3600 * 8
MAX_FAILS = 5
LOCK_SECS = 300
ITER = 200_000

SESSIONS = {}          # token -> {"user", "csrf", "exp", "flash"}
FAILS = {}             # ip -> [count, first_ts]


# ---------------- admin login ----------------
def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), ITER).hex()


def set_admin(username, password):
    if len(password) < 8:
        raise SystemExit("password အနည်းဆုံး 8 လုံး")
    salt = secrets.token_hex(16)
    os.makedirs(zvpn.HOME, exist_ok=True)
    with open(PANEL_DB, "w") as f:
        json.dump({"user": username, "salt": salt, "hash": _hash(password, salt)}, f)
    os.chmod(PANEL_DB, 0o600)
    print(f"admin '{username}' saved")


def check_login(username, password):
    try:
        with open(PANEL_DB) as f:
            db = json.load(f)
    except (OSError, ValueError):
        return False
    ok_user = hmac.compare_digest(username, db["user"])
    ok_pass = hmac.compare_digest(_hash(password, db["salt"]), db["hash"])
    return ok_user and ok_pass


def too_many_fails(ip):
    rec = FAILS.get(ip)
    if not rec:
        return False
    if time.time() - rec[1] > LOCK_SECS:
        FAILS.pop(ip, None)
        return False
    return rec[0] >= MAX_FAILS


def note_fail(ip):
    rec = FAILS.get(ip)
    if not rec or time.time() - rec[1] > LOCK_SECS:
        FAILS[ip] = [1, time.time()]
    else:
        rec[0] += 1


# ---------------- pages ----------------
CSS = """
body{font-family:sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:16px}
h2{margin:8px 0}
.box{background:#1a1d24;border-radius:10px;padding:14px;margin-bottom:14px}
input,select{background:#0f1115;color:#e6e6e6;border:1px solid #333;border-radius:6px;padding:8px;margin:3px 0;width:100%;box-sizing:border-box}
button{background:#2d7ff9;color:#fff;border:0;border-radius:6px;padding:8px 12px;margin:3px 2px}
button.red{background:#d64545} button.gray{background:#555}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{border-bottom:1px solid #2a2d35;padding:6px;text-align:left}
.ok{color:#5fd38d} .bad{color:#ff7b7b} .msg{padding:8px;border-radius:6px;margin-bottom:10px}
.msg.ok{background:#16351f} .msg.err{background:#3a1717}
.row{display:flex;gap:6px;flex-wrap:wrap}
.row>*{flex:1 1 140px}
form.inline{display:inline}
"""


def page(title, body):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body>{body}</body></html>"""


def login_page(msg=""):
    m = f'<div class="msg err">{html.escape(msg)}</div>' if msg else ""
    return page("Login", f"""
<div class="box" style="max-width:360px;margin:40px auto">
<h2>ZIVPN Panel</h2>{m}
<form method="post" action="/login">
<input name="username" placeholder="Admin username" autocomplete="username" required>
<input name="password" type="password" placeholder="Password" autocomplete="current-password" required>
<button type="submit" style="width:100%;margin-top:8px">Login</button>
</form></div>""")


def dashboard(sess, flash):
    db = zvpn.load_db()
    online = zvpn.read_online()
    counts = {}
    for s in online.get("sessions", []):
        counts.setdefault(s["user"], set()).add(s["ip"])
    rows = []
    for name, u in sorted(db["users"].items()):
        st = zvpn.status_of(u)
        cls = "ok" if st == "active" else "bad"
        n = len(counts.get(name, ()))
        csrf = sess["csrf"]
        rows.append(f"""
<tr><td>{html.escape(name)}</td><td>{html.escape(u['password'])}</td>
<td>{u['expire']}</td><td>{u['limit']}</td><td>{n}</td>
<td class="{cls}">{st}</td>
<td>
 <form class="inline" method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
 <input type="hidden" name="action" value="{'unlock' if st=='locked' else 'lock'}">
 <input type="hidden" name="user" value="{html.escape(name)}">
 <button class="gray">{'Unlock' if st=='locked' else 'Lock'}</button></form>
 <form class="inline" method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
 <input type="hidden" name="action" value="delete"><input type="hidden" name="user" value="{html.escape(name)}">
 <button class="red">Delete</button></form>
</td></tr>""")
    table = "".join(rows) or '<tr><td colspan="7">user မရှိသေးပါ</td></tr>'
    m = ""
    if flash:
        cls = "ok" if flash[0] else "err"
        m = f'<div class="msg {cls}">{html.escape(flash[1])}</div>'
    csrf = sess["csrf"]
    online_txt = "monitor မ run သေး" if online.get("ts", 0) == 0 else (
        f"unmapped session: {online.get('unmapped', 0)}")
    return page("ZIVPN Panel", f"""
<div class="row"><h2>ZIVPN Panel</h2>
<div style="text-align:right"><a href="/logout" style="color:#8ab4ff">Logout</a></div></div>
{m}
<div class="box"><h2>User အသစ်</h2>
<form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="action" value="create">
<div class="row">
<input name="user" placeholder="username" required>
<input name="password" placeholder="ZIVPN password (4+)" required>
<input name="days" type="number" value="30" min="1" placeholder="ရက်">
<input name="limit" type="number" value="1" min="1" placeholder="device limit">
</div>
<button style="margin-top:6px">Create</button></form></div>

<div class="box"><h2>User များ</h2>
<table><tr><th>User</th><th>Password</th><th>Expire</th><th>Limit</th><th>Online</th><th>Status</th><th>Action</th></tr>
{table}</table>
<p style="font-size:12px;color:#888">{online_txt}</p></div>

<div class="box"><h2>သက်တမ်းတိုး / Limit / Password</h2>
<form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="action" value="renew">
<div class="row"><input name="user" placeholder="username" required>
<input name="days" type="number" value="30" min="1"><button>Renew</button></div></form>
<form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="action" value="setlimit">
<div class="row"><input name="user" placeholder="username" required>
<input name="limit" type="number" min="1" placeholder="limit"><button>Set limit</button></div></form>
<form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="action" value="setpass">
<div class="row"><input name="user" placeholder="username" required>
<input name="password" placeholder="password အသစ်"><button>Set password</button></div></form>
</div>""")


# ---------------- request handling ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "zvpn-panel"

    def log_message(self, fmt, *args):
        sys.stderr.write("[panel] " + (fmt % args) + "\n")

    # --- helpers
    def _session(self):
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        tok = c.get("zsess")
        if not tok:
            return None
        s = SESSIONS.get(tok.value)
        if not s or s["exp"] < time.time():
            SESSIONS.pop(tok.value, None)
            return None
        return s

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, where, headers=None):
        self._send(303, "", headers=[("Location", where)] + (headers or []))

    def _form(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > 10_000:
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    # --- routes
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            return self._send(200, login_page())
        if path == "/logout":
            c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
            if c.get("zsess"):
                SESSIONS.pop(c["zsess"].value, None)
            return self._redirect("/login", [("Set-Cookie", "zsess=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict")])
        if path == "/":
            sess = self._session()
            if not sess:
                return self._redirect("/login")
            flash, sess["flash"] = sess.get("flash"), None
            return self._send(200, dashboard(sess, flash))
        self._send(404, page("404", "<p>not found</p>"))

    def do_POST(self):
        path = self.path.split("?")[0]
        form = self._form()
        if path == "/login":
            ip = self.client_address[0]
            if too_many_fails(ip):
                return self._send(429, login_page(f"လွန်ကျူးမှု များလို့ {LOCK_SECS//60} မိနစ် စောင့်ပါ"))
            if not check_login(form.get("username", ""), form.get("password", "")):
                note_fail(ip)
                time.sleep(1)
                return self._send(200, login_page("username / password မှားနေပါတယ်"))
            FAILS.pop(ip, None)
            tok = secrets.token_urlsafe(32)
            SESSIONS[tok] = {"user": form["username"], "csrf": secrets.token_urlsafe(24),
                             "exp": time.time() + SESSION_TTL, "flash": None}
            return self._redirect("/", [("Set-Cookie",
                f"zsess={tok}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}")])

        if path == "/action":
            sess = self._session()
            if not sess:
                return self._redirect("/login")
            if not hmac.compare_digest(form.get("csrf", ""), sess["csrf"]):
                sess["flash"] = (False, "form token မှား (refresh လုပ်ပြီး ထပ်ကြိုးစားပါ)")
                return self._redirect("/")
            sess["flash"] = self._do_action(form)
            return self._redirect("/")

        self._send(404, page("404", "<p>not found</p>"))

    def _do_action(self, f):
        act = f.get("action", "")
        user = f.get("user", "").strip()
        try:
            if act == "create":
                msg = zvpn.cmd_create(user, f.get("password", ""), int(f.get("days") or 30), int(f.get("limit") or 1))
            elif act == "delete":
                msg = zvpn.cmd_delete(user)
            elif act == "renew":
                msg = zvpn.cmd_renew(user, int(f.get("days") or 30))
            elif act == "lock":
                msg = zvpn.cmd_lock(user, True)
            elif act == "unlock":
                msg = zvpn.cmd_lock(user, False)
            elif act == "setlimit":
                msg = zvpn.cmd_setlimit(user, int(f.get("limit") or 0))
            elif act == "setpass":
                msg = zvpn.cmd_setpass(user, f.get("password", ""))
            else:
                return (False, "action မသိပါ")
            return (True, msg)
        except (zvpn.CmdError, ValueError) as e:
            return (False, str(e))


def serve():
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"zvpn-panel listening on {BIND}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "set-admin":
        set_admin(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "serve":
        serve()
    else:
        print(__doc__)
