#!/usr/bin/env bash
# Explicit dependency installation only. No ROS node, camera, service or motor startup.
set -euo pipefail
unset PYTHONPATH
export PYTHONNOUSERSITE=1
ONLINE_TOOLS=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ONLINE_ENV=${1:-"$ONLINE_TOOLS/../../.runtime/collection-writer-v13"}
[[ "$ONLINE_ENV" = /* ]] || { echo 'Use an absolute environment path'; exit 2; }
if [[ -f "$ONLINE_ENV/ONLINE_WRITER_READY" ]]; then
  PYTHONNOUSERSITE=1 "$ONLINE_ENV/bin/python" -B "$ONLINE_TOOLS/check_online_runtime.py"
  exit
fi
# Dependencies are public downloads. Do not inherit a desktop/SSH proxy pointing
# at a nonexistent service on the robot. These settings affect this child shell
# only; never edit the user's shell, pip/git configuration or system environment.
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset no_proxy NO_PROXY PIP_PROXY GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT
export PIP_CONFIG_FILE=/dev/null GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
if [[ -n "${SONIC_INSTALL_PROXY:-}" ]]; then
  export http_proxy="$SONIC_INSTALL_PROXY" https_proxy="$SONIC_INSTALL_PROXY"
  echo 'DEPENDENCY_NETWORK=explicit_proxy (installation process only)'
else
  echo 'DEPENDENCY_NETWORK=direct (inherited proxy ignored; installation process only)'
fi
unset SONIC_INSTALL_PROXY
trap 'echo "DEPENDENCY_PREPARE_FAILED: 依赖准备未完成，尚未进入代码替换或服务重启；请保留上面的下载/检查错误。" >&2' ERR
if [[ ! -x "$ONLINE_ENV/bin/python" ]]; then
  /usr/bin/python3 -m venv --without-pip "$ONLINE_ENV"
fi
ONLINE_PYTHON="$ONLINE_ENV/bin/python"
export PYTHONNOUSERSITE=1
# Vendored official pip wheel bootstraps hosts without python3-venv/ensurepip.
"$ONLINE_PYTHON" -B - "$ONLINE_TOOLS/bootstrap/pip-26.1-py3-none-any.whl" <<'PYBOOT'
import sys
wheel=sys.argv[1]
sys.path.insert(0,wheel)
from pip._internal.cli.main import main
raise SystemExit(main(['install','--no-index','--no-deps',wheel]))
PYBOOT
if "$ONLINE_PYTHON" -B -c 'import importlib.metadata as m; assert m.version("torch")=="2.6.0+cpu" and m.version("torchvision")=="0.21.0+cpu"' 2>/dev/null; then
  echo 'CPU_TORCH_ALREADY_INSTALLED: reuse; no download'
else
  "$ONLINE_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.6.0' 'torchvision==0.21.0'
fi
if "$ONLINE_PYTHON" -B - "$ONLINE_TOOLS/ONLINE_RUNTIME_LOCK.txt" "$ONLINE_TOOLS/requirements-online.txt" <<'PYCHECK'
import importlib.metadata as metadata
from pathlib import Path
import sys
try:
    for filename in sys.argv[1:]:
        for line in Path(filename).read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            name, version = line.strip().split('==')
            if metadata.version(name) != version:
                raise ValueError(name)
except (metadata.PackageNotFoundError, ValueError):
    raise SystemExit(1)
PYCHECK
then
  echo 'ONLINE_BASE_ALREADY_INSTALLED: reuse; no download'
else
  "$ONLINE_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir -r "$ONLINE_TOOLS/requirements-online.txt" -c "$ONLINE_TOOLS/ONLINE_RUNTIME_LOCK.txt"
fi
if ! "$ONLINE_PYTHON" -B "$ONLINE_TOOLS/check_online_runtime.py" --source-only 2>/dev/null; then
  "$ONLINE_PYTHON" -B "$ONLINE_TOOLS/check_online_runtime.py" --check-wheel
  "$ONLINE_PYTHON" -m pip install --disable-pip-version-check --no-index --no-deps --force-reinstall "$ONLINE_TOOLS/bootstrap/lerobot-0.1.0-py3-none-any.whl"
fi
"$ONLINE_PYTHON" -B "$ONLINE_TOOLS/check_online_runtime.py"
printf '%s\n' 'NVIDIA_SONIC_ONLINE_WRITER_V13' > "$ONLINE_ENV/ONLINE_WRITER_READY"
