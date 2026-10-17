#!/usr/bin/env python3
"""zvpn: ZIVPN multi-user manager.

  zvpn                              interactive menu
  zvpn create <user> <pass> <days> <limit>
  zvpn delete <user>
  zvpn renew <user> <days>
  zvpn lock <user> | unlock <user>
  zvpn setlimit <user> <n>
  zvpn setpass <user> <pass>
  zvpn list                         all users + status
  zvpn online                       live sessions per user (from monitor)
  zvpn debug                        show recent connect log lines (format check)
  zvpn sync                         rewrite zivpn passwords from users (restart if changed)
  zvpn monitor                      daemon: expiry sync, online tracking, device limit
"""
import json, os, re, secrets, shlex, shutil, subprocess, sys, time
from datetime import date, timedelta

HOME = os.environ.get("ZVPN_HOME", "/etc/zivpn-mu")
DB = os.path.join(HOME, "users.json")
ONLINE = os.path.join(HOME, "online.json")
CFG = os.environ.get("ZIVPN_CFG", "/etc/zivpn/config.json")
SERVICE = "zivpn"
SERVER_PORT = 5667
PORT_RANGE = (6000, 19999)          # iptables DNAT range -> 5667
INTERVAL = int(os.environ.get("ZVPN_INTERVAL", "5"))
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")
ADDR_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})")
CT_RE = re.compile(r"src=(\S+) dst=(\S+) sport=(\d+) dport=(\d+)")
RULE_COMMENT = "zvpn-mu"


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except OSError:
        return None


# ---------------- database ----------------
def load_db():
    if os.path.exists(DB):
        with open(DB) as f:
            return json.load(f)
    db = {"users": {}, "placeholder": "zv-" + secrets.token_hex(6)}
    save_db(db)
    return db


def save_db(db):
    os.makedirs(HOME, exist_ok=True)
    tmp = DB + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2)
    os.replace(tmp, DB)


def status_of(u, today=None):
    today = today or date.today()
    if u.get("locked"):
        return "locked"
    exp = u.get("expire")
    if exp and date.fromisoformat(exp) < today:
        return "expired"
    return "active"


def is_active(u):
    return status_of(u) == "active"


# ---------------- ZIVPN config sync ----------------
def restart_service():
    run(["systemctl", "restart", SERVICE])


def sync_config(db=None):
    """Write active users' passwords into zivpn auth.config. Restart only on change."""
    db = db or load_db()
    if not os.path.exists(CFG):
        return False
    passwords = sorted({u["password"] for u in db["users"].values() if is_active(u)})
    if not passwords:
        passwords = [db["placeholder"]]          # zivpn needs a non-empty list
    with open(CFG) as f:
        cfg = json.load(f)
    auth = cfg.setdefault("auth", {})
    if auth.get("mode") == "passwords" and auth.get("config") == passwords:
        return False
    auth["mode"] = "passwords"
    auth["config"] = passwords
    shutil.copy2(CFG, CFG + ".bak")
    tmp = CFG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CFG)
    restart_service()
    return True


# ---------------- user commands ----------------
class CmdError(Exception):
    pass


def _check_name(db, user):
    if not NAME_RE.match(user):
        raise CmdError("username မှားနေပါတယ် (a-z A-Z 0-9 _ . - , 2-32 လုံး)")


def _check_pass(db, password, skip=None):
    if len(password) < 4 or " " in password:
        raise CmdError("password အနည်းဆုံး 4 လုံး၊ space မပါရ")
    for name, u in db["users"].items():
        if name != skip and u["password"] == password:
            raise CmdError(f"ဒီ password ကို '{name}' က သုံးနေပြီ")


def cmd_create(user, password, days, limit):
    db = load_db()
    _check_name(db, user)
    if user in db["users"]:
        raise CmdError("ဒီ user ရှိပြီးသား")
    _check_pass(db, password)
    today = date.today()
    db["users"][user] = {
        "password": password,
        "expire": (today + timedelta(days=days)).isoformat(),
        "limit": limit,
        "locked": False,
        "created": today.isoformat(),
    }
    save_db(db)
    sync_config(db)
    return f"created {user} (expire {db['users'][user]['expire']}, limit {limit})"


def cmd_delete(user):
    db = load_db()
    if user not in db["users"]:
        raise CmdError("User မရှိပါ")
    del db["users"][user]
    save_db(db)
    sync_config(db)              # next monitor cycle blocks any live sessions
    return f"deleted {user}"


def cmd_renew(user, days):
    db = load_db()
    u = db["users"].get(user)
    if not u:
        raise CmdError("User မရှိပါ")
    u["expire"] = (date.today() + timedelta(days=days)).isoformat()
    u["locked"] = False
    save_db(db)
    sync_config(db)
    return f"renewed {user} until {u['expire']}"


def cmd_lock(user, locked):
    db = load_db()
    u = db["users"].get(user)
    if not u:
        raise CmdError("User မရှိပါ")
    u["locked"] = locked
    save_db(db)
    sync_config(db)
    return f"{'locked' if locked else 'unlocked'} {user}"


def cmd_setlimit(user, limit):
    db = load_db()
    u = db["users"].get(user)
    if not u:
        raise CmdError("User မရှိပါ")
    if limit < 1:
        raise CmdError("limit က 1 နဲ့ အထက် ဖြစ်ရမယ်")
    u["limit"] = limit
    save_db(db)
    return f"{user} limit = {limit}"


def cmd_setpass(user, password):
    db = load_db()
    u = db["users"].get(user)
    if not u:
        raise CmdError("User မရှိပါ")
    _check_pass(db, password, skip=user)
    u["password"] = password
    save_db(db)
    sync_config(db)
    return f"password updated for {user}"


def read_online():
    try:
        with open(ONLINE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"ts": 0, "sessions": [], "unmapped": 0}


def cmd_list():
    db = load_db()
    online = read_online()
    counts = {}
    for s in online["sessions"]:
        counts.setdefault(s["user"], set()).add(s["ip"])
    lines = [f"{'USER':<16}{'PASSWORD':<16}{'EXPIRE':<12}{'LIMIT':<7}{'ONLINE':<8}STATUS"]
    for name, u in sorted(db["users"].items()):
        lines.append(f"{name:<16}{u['password']:<16}{u['expire']:<12}{u['limit']:<7}"
                     f"{len(counts.get(name, ())):<8}{status_of(u)}")
    if not db["users"]:
        lines.append("(user မရှိသေးပါ)")
    return "\n".join(lines)


def cmd_online():
    online = read_online()
    age = int(time.time() - online.get("ts", 0))
    if online.get("ts", 0) == 0:
        return "monitor မ run သေးပါ (systemctl start zvpn-monitor)"
    out = [f"(monitor data {age}s အရင်)"]
    by_user = {}
    for s in online["sessions"]:
        by_user.setdefault(s["user"], []).append(s)
    if not by_user:
        out.append("online user မရှိပါ")
    for user, sess in sorted(by_user.items()):
        ips = sorted({s["ip"] for s in sess})
        blocked = sum(1 for s in sess if s["blocked"])
        out.append(f"{user}: {len(ips)} device  ({', '.join(ips)})  blocked sessions={blocked}")
    if online.get("unmapped"):
        out.append(f"မသိရသေးတဲ့ session: {online['unmapped']} (debug ကြည့်ပါ)")
    return "\n".join(out)


def cmd_debug():
    db = load_db()
    lines = read_log_tail(200)
    hits = [l for l in lines if "connect" in l.lower() and "disconnect" not in l.lower()]
    out = [f"connect line {len(hits)} ခု တွေ့တယ်"]
    for l in hits[-5:]:
        pw_found = [n for n, u in db["users"].items() if pw_in_line(u["password"], l)]
        out.append(f"  {l.strip()[:200]}  -> password match: {pw_found or 'မတွေ့'}")
    return "\n".join(out)


# ---------------- monitor helpers ----------------
def read_log_tail(n=800):
    r = run(["journalctl", "-u", SERVICE, "-n", str(n), "-o", "cat", "--no-pager"])
    return r.stdout.splitlines() if r and r.returncode == 0 else []


def read_conntrack():
    r = run(["conntrack", "-L", "-p", "udp"])
    return r.stdout if r and r.returncode == 0 else ""


def pw_in_line(pw, line):
    return re.search(r"(?<![\w.\-])" + re.escape(pw) + r"(?![\w.\-])", line) is not None


def parse_connect_lines(lines, pw_to_user):
    """{(ip, port): user} for 'connected' log lines that contain a known password."""
    out = {}
    for line in lines:
        low = line.lower()
        if "connect" not in low or "disconnect" in low:
            continue
        m = ADDR_RE.search(line)
        if not m:
            continue
        for pw, user in pw_to_user.items():
            if pw_in_line(pw, line):
                out[(m.group(1), int(m.group(2)))] = user
                break
    return out


def parse_conntrack(text):
    """Set of (client_ip, client_port) for UDP flows into the ZIVPN port(s)."""
    sessions = set()
    for line in text.splitlines():
        m = CT_RE.search(line)
        if not m:
            continue
        src, _dst, sport, dport = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        if dport == SERVER_PORT or PORT_RANGE[0] <= dport <= PORT_RANGE[1]:
            sessions.add((src, sport))
    return sessions


def _ipt_rule(key):
    ip, port = key
    return ["-p", "udp", "-s", ip, "--sport", str(port), "-m", "comment",
            "--comment", RULE_COMMENT, "-j", "DROP"]


def _ipt(args):
    r = run(["iptables"] + args)
    return bool(r and r.returncode == 0)


def block(key):
    rule = _ipt_rule(key)
    if not _ipt(["-C", "INPUT"] + rule):
        _ipt(["-I", "INPUT"] + rule)


def unblock(key):
    rule = _ipt_rule(key)
    for _ in range(5):
        if not _ipt(["-C", "INPUT"] + rule):
            break
        _ipt(["-D", "INPUT"] + rule)


def monitor_cycle(state):
    db = load_db()
    sync_config(db)
    now = time.time()
    pw_to_user = {u["password"]: n for n, u in db["users"].items()}

    # learn ip:port -> user from connect logs (kept while the flow is alive)
    for i, (key, user) in enumerate(parse_connect_lines(read_log_tail(), pw_to_user).items()):
        # log order breaks ties, so the earliest connection is the one that is kept
        state["learned"].setdefault(key, {"user": user, "first": now + i * 1e-3})

    alive = parse_conntrack(read_conntrack())
    for key in list(state["learned"]):
        if key not in alive:
            del state["learned"][key]

    # group live sessions by user
    per_user = {}
    unmapped = 0
    for key in alive:
        info = state["learned"].get(key)
        if info is None:
            unmapped += 1
            continue
        per_user.setdefault(info["user"], []).append((key, info["first"]))

    # decide which sessions must be blocked
    want_block = set()
    sessions_out = []
    for user, sess in per_user.items():
        u = db["users"].get(user)
        if u is None or not is_active(u):
            limit = 0
        else:
            limit = int(u.get("limit", 1))
        first_by_ip = {}
        for key, first in sess:
            first_by_ip[key[0]] = min(first, first_by_ip.get(key[0], first))
        allowed = set(sorted(first_by_ip, key=lambda ip: first_by_ip[ip])[:limit])
        for key, first in sess:
            blocked = key[0] not in allowed
            if blocked:
                want_block.add(key)
            sessions_out.append({"user": user, "ip": key[0], "port": key[1],
                                 "since": int(first), "blocked": blocked})

    for key in want_block - state["blocked"]:
        block(key)
    for key in state["blocked"] - want_block:
        unblock(key)
    state["blocked"] = want_block

    tmp = ONLINE + ".tmp"
    os.makedirs(HOME, exist_ok=True)
    with open(tmp, "w") as f:
        json.dump({"ts": int(now), "sessions": sessions_out, "unmapped": unmapped}, f, indent=2)
    os.replace(tmp, ONLINE)


def clear_stale_rules():
    """Remove DROP rules left by a previous monitor run (state is in memory only)."""
    r = run(["iptables", "-S", "INPUT"])
    if not r or r.returncode != 0:
        return
    for line in r.stdout.splitlines():
        if RULE_COMMENT in line and line.startswith("-A INPUT "):
            args = shlex.split(line)[2:]          # drop "-A INPUT"
            _ipt(["-D", "INPUT"] + args)


def cmd_monitor():
    clear_stale_rules()
    state = {"learned": {}, "blocked": set()}
    while True:
        try:
            monitor_cycle(state)
        except Exception as e:  # keep the daemon alive
            print(f"[monitor] {e}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


# ---------------- interactive menu ----------------
MENU = """
==== ZIVPN Multi-user ====
 1) Create user
 2) Delete user
 3) Renew user
 4) Lock / Unlock user
 5) Change device limit
 6) Change password
 7) User list
 8) Online now
 9) Debug (log format)
 0) Exit
"""


def _ask(p):
    return input(p).strip()


def menu():
    while True:
        print(MENU)
        c = _ask("Select: ")
        try:
            if c == "1":
                print(cmd_create(_ask("Username: "), _ask("Password: "),
                                 int(_ask("Days (30): ") or 30), int(_ask("Device limit (1): ") or 1)))
            elif c == "2":
                print(cmd_delete(_ask("Username: ")))
            elif c == "3":
                print(cmd_renew(_ask("Username: "), int(_ask("Days (30): ") or 30)))
            elif c == "4":
                u = _ask("Username: ")
                lock = _ask("1=lock 2=unlock: ") == "1"
                print(cmd_lock(u, lock))
            elif c == "5":
                print(cmd_setlimit(_ask("Username: "), int(_ask("Limit: "))))
            elif c == "6":
                print(cmd_setpass(_ask("Username: "), _ask("New password: ")))
            elif c == "7":
                print(cmd_list())
            elif c == "8":
                print(cmd_online())
            elif c == "9":
                print(cmd_debug())
            elif c == "0":
                return
        except (CmdError, ValueError) as e:
            print(f"[x] {e}")
        input("\nEnter ...")


def main(argv):
    if len(argv) < 2:
        return menu()
    cmd, a = argv[1], argv[2:]
    if os.geteuid() != 0 and cmd != "list":
        print("[x] root နဲ့ run ပါ")
        return 1
    try:
        if cmd == "create" and len(a) == 4:
            out = cmd_create(a[0], a[1], int(a[2]), int(a[3]))
        elif cmd == "delete" and len(a) == 1:
            out = cmd_delete(a[0])
        elif cmd == "renew" and len(a) == 2:
            out = cmd_renew(a[0], int(a[1]))
        elif cmd in ("lock", "unlock") and len(a) == 1:
            out = cmd_lock(a[0], cmd == "lock")
        elif cmd == "setlimit" and len(a) == 2:
            out = cmd_setlimit(a[0], int(a[1]))
        elif cmd == "setpass" and len(a) == 2:
            out = cmd_setpass(a[0], a[1])
        elif cmd == "list":
            out = cmd_list()
        elif cmd == "online":
            out = cmd_online()
        elif cmd == "debug":
            out = cmd_debug()
        elif cmd == "sync":
            out = "config updated" if sync_config() else "config already up to date"
        elif cmd == "monitor":
            return cmd_monitor()
        else:
            print(__doc__)
            return 1
    except (CmdError, ValueError) as e:
        print(f"[x] {e}")
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
