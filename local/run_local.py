"""Run the whole of MallT on this computer without Docker (start.bat / start.sh call this).

    uv run --project backend python local/run_local.py

It starts, in order:
  1. PostgreSQL from the `pgserver` wheel (real Postgres binaries, no installer, no admin rights),
     with its data in local/data/postgres. Port 55433, local connections only.
  2. The API (uvicorn) on 127.0.0.1:8000, after `alembic upgrade head`.
  3. The website (the prebuilt Next.js server in frontend-build/, or frontend/.next/standalone).
  4. A small reverse proxy on http://localhost:8080 that plays nginx's part: /api and /ws go to
     the API, /media serves the demo photos from local/data/media, everything else goes to the
     website.
Then it adds the demo mall (first run, or when the demo has a newer version), starts the demo
kitchens (restaurants other than Burger Hub and Chai Kadai accept and cook orders on their own),
opens the browser and runs until Ctrl+C or the window is closed. Logs go to local/logs/.
"""

import asyncio
import json
import mimetypes
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "local"
DATA = LOCAL / "data" / "postgres"
LOGS = LOCAL / "logs"
MEDIA = LOCAL / "data" / "media"  # demo photos (seed_demo.py puts them here)
WIN = os.name == "nt"

PG_PORT = 55433
API_PORT = 8000
WEB_PORT = 3000
PROXY_PORT = 8080
DB_URL = f"postgresql+asyncpg://mallt@127.0.0.1:{PG_PORT}/mallt"

children: list[subprocess.Popen[bytes]] = []


def say(msg: str) -> None:
    print(msg, flush=True)


def fail(msg: str) -> "None":
    say("\nERROR: " + msg)
    stop_all()
    sys.exit(1)


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port: int, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_busy(port):
            return True
        time.sleep(0.5)
    return False


def wait_http(url: str, what: str, seconds: int = 120) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    fail(f"{what} did not start. See {LOGS}.")


# ---- 1. PostgreSQL -------------------------------------------------------------------------------


def pg_bin() -> Path:
    """Postgres binaries shipped inside the pgserver wheel (Python 3.12 build, run by uv)."""
    uv = os.environ.get("UV") or shutil.which("uv") or "uv"
    code = "import pgserver, os; print(os.path.dirname(pgserver.__file__))"
    out = subprocess.run(
        [
            uv,
            "run",
            "-q",
            "--no-project",
            "--python",
            "3.12",
            "--with",
            "pgserver==0.1.4",
            "python",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        fail("could not download the Postgres binaries:\n" + out.stderr[-2000:])
    path = Path(out.stdout.strip().splitlines()[-1]) / "pginstall" / "bin"
    return path


def exe(bin_dir: Path, name: str) -> str:
    return str(bin_dir / (name + (".exe" if WIN else "")))


def pg_run(args: list[str], timeout: int, detach: bool = False) -> tuple[int, str]:
    """Run a Postgres tool and return (exit code, output).

    Output goes to a temp file, never a pipe: on Windows `pg_ctl start` hands its pipes to the
    server it launches, which keeps them open forever, so reading a pipe would wait forever.
    """
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        try:
            # detach (Windows): no console, so Ctrl+C or closing the window cannot crash the
            # database mid-write; MallT stops it cleanly itself.
            flags = 0x00000008 | 0x00000200 if (detach and WIN) else 0  # DETACHED | NEW_GROUP
            code = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                timeout=timeout,
                creationflags=flags,
            ).returncode
        except subprocess.TimeoutExpired:
            code = -1
        out.seek(0)
        return code, out.read()


def pg_log_tail() -> str:
    log = LOGS / "postgres.log"
    return log.read_text(errors="replace")[-2000:] if log.exists() else ""


READY = DATA / "mallt-ready"  # written once initdb and our settings are complete


def start_postgres() -> Path:
    bin_dir = pg_bin()
    conf = DATA / "postgresql.conf"
    if not READY.exists() and conf.exists() and "# MallT local" in conf.read_text(errors="replace"):
        READY.write_text("ok\n", encoding="utf-8")  # set up by an older start.bat
    if DATA.exists() and not READY.exists() and not port_busy(PG_PORT):
        # An earlier first run was interrupted half way. Start the database again from scratch.
        shutil.rmtree(DATA, ignore_errors=True)
    if not READY.exists():
        say("  first run: creating the database (takes under a minute)")
        DATA.mkdir(parents=True, exist_ok=True)
        code, out = pg_run(
            [
                exe(bin_dir, "initdb"),
                "-D",
                str(DATA),
                "-U",
                "mallt",
                "-A",
                "trust",
                "-E",
                "UTF8",
                "--locale=C",
            ],
            timeout=300,
        )
        if code != 0:
            fail("creating the database failed:\n" + out[-2000:])
        with open(DATA / "postgresql.conf", "a", encoding="utf-8") as f:
            f.write(
                f"\n# MallT local\nport = {PG_PORT}\nlisten_addresses = '127.0.0.1'\n"
                "unix_socket_directories = ''\nfsync = off\n"
            )
        READY.write_text("ok\n", encoding="utf-8")
    if port_busy(PG_PORT):
        if pg_ready(bin_dir, seconds=20):
            say("  database already running")
            return bin_dir
        say("  the database from an earlier run is stuck; restarting it")
        force_stop_postgres(bin_dir)
    code, out = pg_run(
        [
            exe(bin_dir, "pg_ctl"),
            "-D",
            str(DATA),
            "-l",
            str(LOGS / "postgres.log"),
            "-w",
            "-t",
            "90",
            "start",
        ],
        timeout=120,
        detach=True,
    )
    if not wait_port(PG_PORT, 30 if code == 0 else 3):
        fail("the database did not start:\n" + out[-1000:] + "\n" + pg_log_tail())
    return bin_dir


def pg_ready(bin_dir: Path, seconds: int) -> bool:
    """True once the database accepts connections (it may still be recovering after a crash)."""
    deadline = time.time() + seconds
    while True:
        code, _ = pg_run(
            [exe(bin_dir, "pg_isready"), "-h", "127.0.0.1", "-p", str(PG_PORT), "-t", "3"],
            timeout=10,
        )
        if code == 0:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(1)


def force_stop_postgres(bin_dir: Path) -> None:
    """Stop a database that holds MallT's port but does not answer (crashed half way)."""
    pg_run([exe(bin_dir, "pg_ctl"), "-D", str(DATA), "-m", "immediate", "-w", "stop"], timeout=30)
    pid_file = DATA / "postmaster.pid"
    if port_busy(PG_PORT) and pid_file.exists():
        first = pid_file.read_text(errors="replace").split("\n", 1)[0].strip()
        if first.isdigit():
            if WIN:
                pg_run(["taskkill", "/F", "/T", "/PID", first], timeout=30)
            else:
                try:
                    os.kill(int(first), signal.SIGKILL)
                except OSError:
                    pass
    if WIN and port_busy(PG_PORT):
        # On Windows the server's child processes share its listening socket, so one can keep
        # the port after the main process is gone. End every postgres.exe of this MallT copy.
        bins = str(LOCAL / "tools").replace("'", "''")
        pg_run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process postgres -ErrorAction SilentlyContinue | Where-Object"
                f" {{ $_.Path -like '{bins}*' }} | Stop-Process -Force",
            ],
            timeout=60,
        )
        for pid, what in _port_owners([PG_PORT]).items():
            if str(ROOT).lower() in what.lower():
                pg_run(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=30)
    if not wait_port_free(PG_PORT, 20):
        fail(
            f"the database from an earlier run is stuck and holds port {PG_PORT}. Restart the"
            " computer, then run start.bat again."
        )
    pid_file.unlink(missing_ok=True)


def wait_port_free(port: int, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not port_busy(port):
            return True
        time.sleep(0.5)
    return not port_busy(port)


def stop_postgres(bin_dir: Path) -> None:
    pg_run([exe(bin_dir, "pg_ctl"), "-D", str(DATA), "-m", "fast", "-w", "stop"], timeout=60)


DEMO_READY = LOCAL / "data" / "demo-ready"  # written once the demo mall is fully set up


def ensure_database() -> None:
    import asyncpg  # the API's own driver

    if not DEMO_READY.exists() and (ROOT / "demo-logins.txt").exists():
        DEMO_READY.write_text("ok\n", encoding="utf-8")  # set up by an older start.bat

    async def go() -> None:
        conn = await asyncpg.connect(
            host="127.0.0.1", port=PG_PORT, user="mallt", database="postgres"
        )
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'mallt'")
            if exists and not DEMO_READY.exists():
                # An earlier start stopped half way through adding the demo. Start it afresh.
                say("  an earlier first run did not finish; setting the demo up again")
                await conn.execute("DROP DATABASE mallt WITH (FORCE)")
                exists = None
            if not exists:
                await conn.execute("CREATE DATABASE mallt")
        finally:
            await conn.close()

    asyncio.run(go())


# ---- 2 + 3. API and website ----------------------------------------------------------------------


def spawn(name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    log = open(LOGS / f"{name}.log", "ab")  # noqa: SIM115 (closed with the process)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0  # type: ignore[attr-defined]
    children.append(
        subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags
        )
    )


def api_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        ENV="dev",
        DATABASE_URL=DB_URL,
        REDIS_URL="",
        SMS_BACKEND="console",  # sign-in codes are written to local/logs/api.log (show-otp.bat)
        COOKIE_SECURE="false",
        PYTHONUNBUFFERED="1",
        # Images are served by the proxy below; anything not on disk falls back to the bucket.
        S3_PUBLIC_BASE_URL="/media",
    )
    return env


def bucket_base() -> str:
    """The real bucket's public address from .env, for images uploaded from the dashboards."""
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("S3_PUBLIC_BASE_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    except OSError:
        pass
    return ""


BUCKET = bucket_base()


def web_dir() -> Path:
    for d in (ROOT / "frontend-build", ROOT / "frontend" / ".next" / "standalone"):
        if (d / "server.js").exists():
            return d
    fail(
        "the website build is missing (frontend-build/). Use the MallT zip, or run"
        " `pnpm build` in frontend/ first."
    )
    raise AssertionError


def node() -> str:
    found = os.environ.get("MALLT_NODE") or shutil.which("node")
    if not found:
        fail("Node.js was not found. start.bat downloads it; on macOS/Linux install Node 22.")
    return str(found)


# ---- 4. Reverse proxy (nginx's job, in ~50 lines) ------------------------------------------------


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    try:
        head = await client_r.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        client_w.close()
        return
    lines = head.decode("latin-1").split("\r\n")
    path = lines[0].split(" ")[1] if " " in lines[0] else "/"
    if path.startswith("/media/"):
        await _media(lines[0].split(" ")[0], path, client_w)
        return
    port = API_PORT if path.startswith(("/api/", "/ws/")) else WEB_PORT
    peer = (client_w.get_extra_info("peername") or ("127.0.0.1",))[0]
    upgrade = any(ln.lower().startswith("upgrade:") for ln in lines)
    out = [lines[0]]
    for ln in lines[1:]:
        key = ln.split(":", 1)[0].lower()
        if (
            not ln
            or key in ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip")
            or (key == "connection" and not upgrade)
        ):
            continue
        out.append(ln)
        if key == "host":
            out.append("X-Forwarded-Host:" + ln.split(":", 1)[1])
    out += [f"X-Forwarded-For: {peer}", f"X-Real-IP: {peer}", "X-Forwarded-Proto: http"]
    if not upgrade:
        out.append("Connection: close")  # one request per connection keeps routing simple
    try:
        up_r, up_w = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        client_w.write(
            b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await client_w.drain()
        client_w.close()
        return
    up_w.write(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))
    await asyncio.gather(_pipe(client_r, up_w), _pipe(up_r, client_w))


async def _media(method: str, path: str, client_w: asyncio.StreamWriter) -> None:
    """/media/<key>: the demo photo on disk, or a redirect to the real bucket."""
    raw = path[len("/media/") :].split("?", 1)[0]
    key = urllib.parse.unquote(raw)
    if any(ord(ch) < 32 or ch == "\x7f" for ch in key):  # no header injection via the key
        client_w.write(
            b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await client_w.drain()
        client_w.close()
        return
    file = (MEDIA / key).resolve()
    if method in ("GET", "HEAD") and file.is_file() and file.is_relative_to(MEDIA.resolve()):
        body = await asyncio.to_thread(file.read_bytes)
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        head = (
            f"HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {len(body)}\r\n"
            "Cache-Control: public, max-age=86400\r\nConnection: close\r\n\r\n"
        )
        client_w.write(head.encode() + (body if method == "GET" else b""))
    elif BUCKET:
        client_w.write(
            f"HTTP/1.1 302 Found\r\nLocation: {BUCKET}/{urllib.parse.quote(key)}\r\nContent-Length: 0\r\n"
            "Connection: close\r\n\r\n".encode()
        )
    else:
        client_w.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    try:
        await client_w.drain()
    finally:
        client_w.close()


def start_proxy() -> None:
    async def serve() -> None:
        server = await asyncio.start_server(_handle, "127.0.0.1", PROXY_PORT, limit=1 << 20)
        async with server:
            await server.serve_forever()

    threading.Thread(target=lambda: asyncio.run(serve()), daemon=True).start()


# ---- 5. Demo kitchens: make the demo feel live ----------------------------------------------------

MANUAL_STORES = {"burger-hub", "chai-point"}  # these wait for a person, as in real life
KITCHEN_STEPS = {"paid": ("accept", 6), "accepted": ("preparing", 5), "preparing": ("ready", 30)}


def start_kitchens() -> None:
    """Restaurants other than Burger Hub and Chai Kadai accept an order a few seconds after it
    is paid, start cooking, and call it ready about half a minute later, so a customer sees the
    progress, the live updates and the "ready" alert without a second person at a counter."""
    import seed_demo

    log = open(LOGS / "kitchen.log", "a", encoding="utf-8")  # noqa: SIM115 (lives with the app)

    def note(msg: str) -> None:
        log.write(time.strftime("%H:%M:%S ") + msg + "\n")
        log.flush()

    def run() -> None:
        token = ""
        stores: list[tuple[str, str]] = []
        seen: dict[tuple[str, str], float] = {}
        while True:
            time.sleep(4)
            try:
                if not token:
                    token = seed_demo.login(seed_demo.ORG_OWNER, seed_demo.PASSWORD)
                    mall = seed_demo.find_mall(token)
                    if mall is None:
                        return
                    stores = [
                        (s["id"], s["name"])
                        for s in seed_demo.call("GET", f"/malls/{mall}/stores", token)
                        if s["slug"] not in MANUAL_STORES
                    ]
                now = time.monotonic()
                for sid, name in stores:
                    page = seed_demo.call("GET", f"/stores/{sid}/orders?view=active", token)
                    for order in page["items"]:
                        step = KITCHEN_STEPS.get(order["status"].lower())
                        if step is None:
                            continue
                        first = seen.setdefault((order["id"], order["status"]), now)
                        if now - first >= step[1]:
                            seed_demo.call(
                                "POST", f"/stores/{sid}/orders/{order['id']}/{step[0]}", token
                            )
                            note(f"{name} order #{order['order_no']}: {step[0]}")
            except seed_demo.ApiFailed as exc:
                if exc.status == 401:
                    token = ""  # the 15-minute access token ran out; sign in again
                elif exc.status == 403:
                    note("the demo owner can no longer manage orders; kitchens stopped")
                    return
                else:
                    note(f"skipped a step: {exc}")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                note(f"API not reachable: {exc}")

    threading.Thread(target=run, daemon=True).start()


# ---- orchestration -------------------------------------------------------------------------------


def _port_owners(ports: list[int]) -> dict[int, str]:
    """PID -> program path of whatever listens on these ports (best effort, no extra packages)."""
    owners: dict[int, str] = {}
    if WIN:
        ps = (
            "Get-NetTCPConnection -State Listen -LocalPort "
            + ",".join(map(str, ports))
            + " -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-CimInstance"
            ' Win32_Process -Filter "ProcessId=$($_.OwningProcess)"; "$($p.ProcessId)|'
            '$($p.ExecutablePath)|$($p.CommandLine)" }'
        )
        try:
            _, out = pg_run(["powershell", "-NoProfile", "-Command", ps], timeout=60)
        except OSError:
            return owners
        for line in out.splitlines():
            pid, _, rest = line.strip().partition("|")
            if pid.isdigit():
                owners[int(pid)] = rest
        return owners
    for port in ports:
        pids: list[str] = []
        if shutil.which("lsof"):
            _, out = pg_run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], timeout=20)
            pids = out.split()
        if not pids and shutil.which("fuser"):
            _, out = pg_run(["fuser", "-n", "tcp", str(port)], timeout=20)
            pids = out.replace(f"{port}/tcp:", " ").split()
        for pid in filter(str.isdigit, pids):
            _, cmd = pg_run(["ps", "-o", "command=", "-p", pid], timeout=10)
            # Next.js renames its process, so also look at where it runs from.
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                cwd = ""
                if shutil.which("lsof"):
                    _, cwd = pg_run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], timeout=10)
            owners[int(pid)] = cmd.strip() + "|" + cwd.strip()
    return owners


def stop_leftovers(ports: list[int]) -> None:
    """Stop a MallT left running by an earlier window (closing a window does not always stop
    what it started). Only processes running from this MallT folder are touched."""
    busy = [p for p in ports if port_busy(p)]
    if not busy:
        return
    root = str(ROOT).lower()
    ours = [
        pid
        for pid, what in _port_owners(busy).items()
        if root in what.lower() and pid != os.getpid()
    ]
    if not ours:
        return
    say("  stopping an earlier MallT that was still running...")
    for pid in ours:
        if WIN:
            pg_run(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=30)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.time() + 20
    while time.time() < deadline and any(port_busy(p) for p in busy):
        time.sleep(0.5)


_job: object = None


def stop_children_with_us() -> None:
    """Windows: put this process in a job that ends its children when it ends, so closing the
    window never leaves the API or website running in the background. The database is already
    running by now and stays out of the job (the next start reuses it)."""
    global _job
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", Basic),
            ("IoInfo", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    if k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        _job = job  # keep the handle open for as long as this process lives


def stop_all() -> None:
    for p in children:
        if p.poll() is None:
            p.terminate()
    for p in children:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def main() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    stop_leftovers([API_PORT, WEB_PORT, PROXY_PORT])
    for port, what in ((API_PORT, "the API"), (WEB_PORT, "the website"), (PROXY_PORT, "MallT")):
        if port_busy(port):
            fail(
                f"port {port} (for {what}) is already in use. Is MallT already running in another"
                " window? Close it, or stop whatever uses that port."
            )

    say("[1/4] Starting the database...")
    bin_dir = start_postgres()
    stop_children_with_us()
    try:
        ensure_database()

        say("[2/4] Starting the API...")
        env = api_env()
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            fail("database migration failed:\n" + r.stdout[-1500:] + r.stderr[-1500:])
        spawn(
            "api",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "mallt.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(API_PORT),
                "--proxy-headers",
            ],
            ROOT / "backend",
            env,
        )
        wait_http(f"http://127.0.0.1:{API_PORT}/api/v1/health", "The API")

        say("[3/4] Starting the website...")
        web = web_dir()
        wenv = dict(
            os.environ,
            API_INTERNAL_URL=f"http://127.0.0.1:{API_PORT}",
            PORT=str(WEB_PORT),
            HOSTNAME="127.0.0.1",
            NODE_ENV="production",
        )
        spawn("web", [node(), "server.js"], web, wenv)
        start_proxy()
        wait_http(f"http://127.0.0.1:{PROXY_PORT}/login", "The website")

        say("[4/4] Getting the demo mall ready...")
        os.environ.update(env)
        sys.path.insert(0, str(LOCAL))
        import seed_demo

        if seed_demo.main() == 0:
            DEMO_READY.write_text("ok\n", encoding="utf-8")
        start_kitchens()

        url = f"http://localhost:{PROXY_PORT}/m/{seed_demo.MALL_SLUG}"
        say(
            f"\nMallT is running.\n  Customer page : {url}\n  Staff sign-in : "
            f"http://localhost:{PROXY_PORT}/login\n  Logins        : demo-logins.txt\n"
            "  Sign-in codes : show-otp.bat\n\nKeep this window open. Close it or press Ctrl+C"
            " to stop MallT."
        )
        webbrowser.open(url)
        while all(p.poll() is None for p in children):
            time.sleep(1)
        fail(f"a part of MallT stopped unexpectedly. See {LOGS}.")
    except KeyboardInterrupt:
        say("\nStopping MallT...")
    finally:
        # A second Ctrl+C (or the console forwarding one) must not cut the clean-up short.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if not WIN:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop_all()
        stop_postgres(bin_dir)
        say("Stopped.")


def stop_or_reset(reset: bool) -> None:
    """stop.bat: stop a database left running (e.g. the window was closed); optionally wipe."""
    stop_leftovers([API_PORT, WEB_PORT, PROXY_PORT])
    if (DATA / "postmaster.pid").exists():
        stop_postgres(pg_bin())
        say("Database stopped.")
    if reset:
        shutil.rmtree(LOCAL / "data", ignore_errors=True)
        (ROOT / "demo-logins.txt").unlink(missing_ok=True)
        say("All local MallT data deleted. The next start.bat begins fresh with the demo mall.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--stop", "--reset"):
        stop_or_reset(sys.argv[1] == "--reset")
        sys.exit(0)
    if not WIN:
        signal.signal(signal.SIGTERM, signal.default_int_handler)  # stop cleanly, like Ctrl+C
    main()
