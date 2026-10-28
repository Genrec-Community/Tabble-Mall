#!/usr/bin/env bash
# Builds the print-agent binary and the Linux release folder and archive.
#
# Run on Linux (WSL Ubuntu is fine): PyInstaller cannot cross-compile, so an ARM
# machine runs this itself. Build on the oldest distro you can: a binary built on a
# new glibc will not start on an older one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

case "$(uname -m)" in
  x86_64) arch=x64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "unsupported CPU: $(uname -m)" >&2; exit 1 ;;
esac

python="${PYTHON:-python3}"
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
  || { echo "Python 3.12 or newer is required (set PYTHON=/path/to/python3.12)." >&2; exit 1; }

# CRLF in a shell script or the unit file is a silent, baffling failure on the target.
if grep -l $'\r' packaging/linux/*.sh packaging/linux/*.service 2>/dev/null; then
  echo "the files above have CRLF line endings; convert them to LF" >&2
  exit 1
fi

venv=".build-venv-linux-$arch"
[ -d "$venv" ] || "$python" -m venv "$venv"
# shellcheck disable=SC1091
. "$venv/bin/activate"
pip install --quiet websockets pytest pytest-asyncio -r requirements-build.txt
python -m pytest -q

stage="dist/linux-$arch"
rm -rf "$stage"
pyinstaller --noconfirm --clean --onefile --name print-agent \
  --collect-submodules websockets \
  --distpath "$stage/pyi" --workpath "build/linux-$arch/work" --specpath "build/linux-$arch" \
  entry.py

bin="$stage/pyi/print-agent"
"$bin" --help >/dev/null

# A missing config must exit 2 with a sentence: that is what a half-installed PC does.
set +e
env -u MALLT_AGENT_URL -u MALLT_AGENT_TOKEN "$bin" --config /nonexistent/agent.toml 2>/dev/null
code=$?
set -e
[ "$code" -eq 2 ] || { echo "smoke run: expected exit 2 for a missing config, got $code" >&2; exit 1; }

folder="$stage/mallt-print-agent"
mkdir -p "$folder"
cp "$bin" agent.example.toml "$folder/"
cp packaging/linux/* "$folder/"
chmod 0755 "$folder/print-agent"
chmod 0755 "$folder"/*.sh 2>/dev/null || true

archive="dist/mallt-print-agent-linux-$arch.tar.gz"
mkdir -p dist
# --mode=go-w: building on a Windows drive (WSL /mnt/d) leaves every file 0777; this keeps
# the archive at 0755/0644 whatever the build disk does.
tar -C "$stage" --owner=0 --group=0 --mode='go-w' -czf "$archive" mallt-print-agent

echo
echo "Built $archive ($(du -h "$archive" | cut -f1))"
