param(
    [string]$Distro = "",
    [string]$LinuxRoot = "~/mortal-rogs-mjx"
)

$ErrorActionPreference = "Stop"

$wslArgs = @()
if ($Distro) {
    $wslArgs += @("-d", $Distro)
}

# Keep bash variables literal. Only the explicit placeholder below is replaced
# by PowerShell before the script is sent into WSL.
$script = @'
set -euo pipefail
ROOT='__LINUX_ROOT__'
mkdir -p "$ROOT"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo 'python3 is required inside WSL.' >&2
  exit 2
fi

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
# Pin the last public MJX release because upstream master currently warns that
# its build is broken. v0.1.0 was released with Python 3.7-3.11 support.
python -m pip install 'mjx==0.1.0'
python - <<'PY'
import mjx

env = mjx.MjxEnv()
obs = env.reset(seed=1)
assert len(obs) == 4, f'Expected 4P MJX, got {len(obs)} players'
print('MJX_OK', getattr(mjx, '__version__', 'unknown'), sorted(obs))
PY
'@
$script = $script.Replace('__LINUX_ROOT__', $LinuxRoot.Replace("'", "'\"'\"'"))

& wsl @wslArgs bash -lc $script
if ($LASTEXITCODE -ne 0) {
    throw "MJX WSL setup failed with exit code $LASTEXITCODE"
}

Write-Host "MJX evaluation runtime installed in WSL at $LinuxRoot"
