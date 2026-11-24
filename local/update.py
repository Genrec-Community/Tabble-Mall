"""Bring this MallT folder up to date with the latest code on GitHub. start.bat runs it first.

It downloads the `jaisamyukth-changes` branch of Genrec-Community/Tabble-Mall as a zip (no git or
GitHub account needed), replaces the code, and keeps everything that is yours: the database
(local/data), logs, downloaded tools, demo-logins.txt and an edited .env. Python packages update
on their own when start.bat runs the API (uv syncs them). The website is rebuilt here only when
its code changed (a few minutes the first time). If GitHub cannot be reached, MallT starts the
version you already have.

Run it with --check to only say whether an update is waiting. Uses the standard library only.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "Genrec-Community/Tabble-Mall"
BRANCH = "jaisamyukth-changes"
PNPM = "pnpm@10.28.0"

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "local"
WORK = LOCAL / "update"
VERSION = LOCAL / "version.txt"  # the commit this folder holds
FRONTEND_HASH = LOCAL / "frontend.hash"  # the frontend code frontend-build was built from
ENV_HASH = LOCAL / "env.hash"  # the .env as shipped, to tell whether you edited it
WIN = os.name == "nt"

# Paths (relative to the MallT folder) an update never touches.
KEEP = {
    ".env",
    "demo-logins.txt",
    "frontend-build",
    "local/data",
    "local/logs",
    "local/tools",
    "local/update",
    "local/version.txt",
    "local/frontend.hash",
    "local/env.hash",
    "backend/.venv",
    "frontend/node_modules",
    "frontend/.next",
}
FRONTEND_SKIP = {"node_modules", ".next", "test-results", "playwright-report", "e2e"}


def say(msg: str) -> None:
    print(msg, flush=True)


def get(url: str, accept: str = "*/*", timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "mallt-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 (fixed https URLs)
        data: bytes = res.read()
        return data


def latest_commit() -> str:
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    return get(url, "application/vnd.github.sha", timeout=10).decode().strip()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def frontend_hash(frontend: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(frontend.rglob("*")):
        rel = p.relative_to(frontend)
        if rel.parts[0] in FRONTEND_SKIP or not p.is_file():
            continue
        h.update(rel.as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def keeps_inside(rel: str) -> bool:
    return any(k.startswith(rel + "/") for k in KEEP)


def remove_old(folder: Path) -> None:
    """Delete the old code, except KEEP paths (and the folders that lead to them)."""
    for child in folder.iterdir():
        rel = child.relative_to(ROOT).as_posix()
        if rel in KEEP:
            continue
        if child.is_dir() and keeps_inside(rel):
            remove_old(child)
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_new(src: Path, dst: Path) -> None:
    for child in src.iterdir():
        target = dst / child.name
        rel = target.relative_to(ROOT).as_posix()
        if rel in KEEP:
            continue
        if child.is_dir():
            target.mkdir(exist_ok=True)
            copy_new(child, target)
        else:
            shutil.copy2(child, target)


def update_env(new_env: Path) -> None:
    """Take the new .env unless you edited yours (e.g. to add Zoho keys)."""
    env = ROOT / ".env"
    if not new_env.exists():
        return
    shipped = ENV_HASH.read_text().strip() if ENV_HASH.exists() else ""
    if not env.exists() or file_hash(env) == shipped:
        shutil.copy2(new_env, env)
        ENV_HASH.write_text(file_hash(env) + "\n")
    elif file_hash(env) != file_hash(new_env):
        shutil.copy2(new_env, ROOT / ".env.latest")
        say("  You edited .env, so it was kept. The new version is in .env.latest.")


def build_website() -> bool:
    """Rebuild frontend-build/ from frontend/ with the Node.js start.bat downloaded."""
    node = os.environ.get("MALLT_NODE") or shutil.which("node")
    if not node:
        say("  Node.js not found; the website was not rebuilt.")
        return False
    node_dir = Path(node).parent
    npx = node_dir / ("npx.cmd" if WIN else "npx")
    if not npx.exists():
        npx = Path(shutil.which("npx") or "npx")
    env = dict(os.environ, PATH=str(node_dir) + os.pathsep + os.environ.get("PATH", ""))
    env.update(NEXT_PUBLIC_API_BASE="", NEXT_TELEMETRY_DISABLED="1", CI="1")
    frontend = ROOT / "frontend"
    log = LOCAL / "logs" / "website-build.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> bool:
        with open(log, "a", encoding="utf-8", errors="replace") as out:
            code = subprocess.run(
                [str(npx), "-y", PNPM, *args],
                cwd=frontend,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
            ).returncode
        return code == 0

    say("  Rebuilding the website (a few minutes; the first time downloads about 300 MB)...")
    log.write_text("", encoding="utf-8")
    # Hoisted node_modules: plain folders, no symlinks, so the built site can be moved.
    if not run("install", "--frozen-lockfile", "--config.node-linker=hoisted"):
        say(f"  Installing the website's packages failed. See {log}.")
        return False
    if not run("build") and not run("build"):  # Next.js sometimes stops once to show a notice
        say(f"  Building the website failed. See {log}.")
        return False
    built = frontend / ".next"
    fresh = WORK / "frontend-build"
    shutil.rmtree(fresh, ignore_errors=True)
    shutil.copytree(built / "standalone", fresh, symlinks=False)
    shutil.copytree(built / "static", fresh / ".next" / "static", dirs_exist_ok=True)
    if (frontend / "public").exists():
        shutil.copytree(frontend / "public", fresh / "public", dirs_exist_ok=True)
    shutil.rmtree(ROOT / "frontend-build", ignore_errors=True)
    shutil.move(str(fresh), ROOT / "frontend-build")
    return True


def stop_running_mallt() -> None:
    """Files a MallT left running still holds open cannot be replaced (Windows), so stop it."""
    sys.path.insert(0, str(LOCAL))
    try:
        import run_local  # stdlib only at import time

        run_local.stop_leftovers([run_local.API_PORT, run_local.WEB_PORT, run_local.PROXY_PORT])
    except Exception as exc:  # noqa: BLE001 - never block an update on this
        say(f"  (could not check for a running MallT: {exc})")


def main() -> int:
    current = VERSION.read_text().strip() if VERSION.exists() else ""
    try:
        latest = latest_commit()
    except Exception as exc:  # noqa: BLE001 - offline, GitHub down, rate limit: just start
        say(f"Could not check for updates ({exc}). Starting the version you have.")
        return 0
    if "--check" in sys.argv:
        say("Up to date." if latest == current else f"An update is waiting ({latest[:7]}).")
        return 0
    if latest == current:
        say(f"MallT is up to date ({latest[:7]}).")
    else:
        say(f"Updating MallT to the latest version ({latest[:7]})...")
        try:
            shutil.rmtree(WORK, ignore_errors=True)
            WORK.mkdir(parents=True)
            archive = WORK / "mallt.zip"
            archive.write_bytes(
                get(f"https://codeload.github.com/{REPO}/zip/{latest}", timeout=300)
            )
            with zipfile.ZipFile(archive) as z:
                z.extractall(WORK / "new")
                for info in z.infolist():  # zipfile drops the executable bit (start.sh)
                    if (info.external_attr >> 16) & 0o111:
                        (WORK / "new" / info.filename).chmod(0o755)
            (new_root,) = [p for p in (WORK / "new").iterdir() if p.is_dir()]
        except Exception as exc:  # noqa: BLE001
            say(f"  The download failed ({exc}). Starting the version you have.")
            return 0
        stop_running_mallt()
        remove_old(ROOT)
        copy_new(new_root, ROOT)
        update_env(new_root / ".env")
        VERSION.write_text(latest + "\n")
        shutil.rmtree(WORK / "new", ignore_errors=True)
        archive.unlink(missing_ok=True)
        say("  Code updated.")

    stored = FRONTEND_HASH.read_text().strip() if FRONTEND_HASH.exists() else ""
    wanted = frontend_hash(ROOT / "frontend")
    if stored != wanted or not (ROOT / "frontend-build" / "server.js").exists():
        stop_running_mallt()
        if build_website():
            FRONTEND_HASH.write_text(wanted + "\n")
            say("  Website rebuilt.")
        else:
            say("  Starting with the previous website; it will try again next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
