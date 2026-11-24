"""Run the whole of MallT on this computer without Docker (start.bat / start.sh call this).

    uv run --project backend python local/run_local.py

It starts, in order:
  1. PostgreSQL from the `pgserver` wheel (real Postgres binaries, no installer, no admin rights),
     with its data in local/data/postgres. Port 55433, local connections only.
  2. The API (uvicorn) on 127.0.0.1:8000, after `alembic upgrade head`.
  3. The website (the prebuilt Next.js server in frontend-build/, or frontend/.next/standalone).
  4. A small reverse proxy on http://localhost:8080 that plays nginx's part: /api and /ws go to
     the API, everything else to the website.
Then it adds the demo mall (first run only), opens the browser and runs until Ctrl+C or the
window is closed. Logs go to local/logs/.
"""

import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "local"
DATA = LOCAL / "data" / "postgres"
LOGS = LOCAL / "logs"
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


def pg_run(args: list[str], timeout: int) -> tuple[int, str]:
    """Run a Postgres tool and return (exit code, output).

    Output goes to a temp file, never a pipe: on Windows `pg_ctl start` hands its pipes to the
    server it launches, which keeps them open forever, so reading a pipe would wait forever.
    """
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        try:
            code = subprocess.run(
                args, stdin=subprocess.DEVNULL, stdout=out, stderr=out, timeout=timeout
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
        say("  database already running")
        return bin_dir
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
    )
    if not wait_port(PG_PORT, 30 if code == 0 else 3):
        fail("the database did not start:\n" + out[-1000:] + "\n" + pg_log_tail())
    return bin_dir


def stop_postgres(bin_dir: Path) -> None:
    pg_run([exe(bin_dir, "pg_ctl"), "-D", str(DATA), "-m", "fast", "-w", "stop"], timeout=60)


def ensure_database() -> None:
    import asyncpg  # the API's own driver

    async def go() -> None:
        conn = await asyncpg.connect(
            host="127.0.0.1", port=PG_PORT, user="mallt", database="postgres"
        )
        try:
            if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'mallt'"):
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
    )
    return env


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


def start_proxy() -> None:
    async def serve() -> None:
        server = await asyncio.start_server(_handle, "127.0.0.1", PROXY_PORT, limit=1 << 20)
        async with server:
            await server.serve_forever()

    threading.Thread(target=lambda: asyncio.run(serve()), daemon=True).start()


# ---- orchestration -------------------------------------------------------------------------------


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
    for port, what in ((API_PORT, "the API"), (WEB_PORT, "the website"), (PROXY_PORT, "MallT")):
        if port_busy(port):
            fail(
                f"port {port} (for {what}) is already in use. Is MallT already running in another"
                " window? Close it, or stop whatever uses that port."
            )

    say("[1/4] Starting the database...")
    bin_dir = start_postgres()
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

        say("[4/4] Adding the demo mall (first run only)...")
        os.environ.update(env)
        sys.path.insert(0, str(LOCAL))
        import seed_demo

        seed_demo.main()

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
