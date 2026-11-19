<#
.SYNOPSIS
  Install quantcore-circuits and its dependencies on a Windows PC (the simulation PC), then test the install.

.DESCRIPTION
  pip cannot run tests while it installs, so this script is the "tests during install":
    1. creates (or reuses) the conda env (default `qcc`, Python 3.11)
    2. installs torch (CPU build), the pinned PyPI packages (requirements\sim-pc.txt), the five upstream snapshots
       from the wheelhouse and quantcore-circuits[all]
    3. runs `qcc selftest` (imports, a Q1 + R1 chip: build, DRC, LOM, job export, ansysedt lookup)
    4. runs `pytest -m "not slow"` when it is run from a repository checkout (tests\ next to this script's folder)
  It stops at the first failure with a message. It never starts AEDT and runs no solver.

  The wheelhouse (dist\wheelhouse\*.whl) is built on the design PC with `python scripts\build_wheelhouse.py` and is
  not in git (dist\ is git-ignored): copy the folder to this PC, or pass -Wheelhouse. Packages other than the six
  wheels (numpy, tqdm, pandas, ...) come from PyPI, so this PC needs internet access for pip.

.PARAMETER EnvName     conda env name (default qcc)
.PARAMETER Wheelhouse  folder with the wheels (default: dist\wheelhouse of the checkout, else .\wheelhouse)
.PARAMETER SkipTorch   do not install torch
.PARAMETER SkipTests   do not run pytest even from a checkout

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_sim_pc.ps1
#>
param(
    [string]$EnvName = "qcc",
    [string]$Wheelhouse = "",
    [switch]$SkipTorch,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TorchVersion = "2.15.0"

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "INSTALL STOPPED: $msg" -ForegroundColor Red
    exit 1
}
function Step([string]$msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }

# ---- the wheelhouse and the requirements ----------------------------------------------------------------------
if (-not $Wheelhouse) {
    foreach ($c in @((Join-Path $Root "dist\wheelhouse"), (Join-Path $PSScriptRoot "wheelhouse"), (Join-Path (Get-Location) "wheelhouse"))) {
        if (Test-Path $c) { $Wheelhouse = $c; break }
    }
}
if (-not $Wheelhouse -or -not (Test-Path $Wheelhouse)) {
    Fail "no wheelhouse found. Build it on the design PC (python scripts\build_wheelhouse.py), copy dist\wheelhouse here and pass -Wheelhouse <folder>."
}
$Wheelhouse = (Resolve-Path $Wheelhouse).Path
$Req = Join-Path $Root "requirements\sim-pc.txt"
if (-not (Test-Path $Req)) { $Req = Join-Path $Wheelhouse "sim-pc.txt" }
if (-not (Test-Path $Req)) { Fail "requirements\sim-pc.txt not found (run from a checkout, or copy it into the wheelhouse folder)." }
$own = @(Get-ChildItem $Wheelhouse -Filter "quantcore_circuits-*.whl")
if ($own.Count -ne 1) { Fail "expected exactly one quantcore_circuits-*.whl in $Wheelhouse, found $($own.Count)." }
$snap = @(Get-ChildItem $Wheelhouse -Filter "*.whl" | Where-Object { $_.Name -notlike "quantcore_circuits-*" })
$need = "kqcircuits", "quantum_metal", "sqcircuit", "qucat", "pyaedt"
foreach ($n in $need) {
    if (-not ($snap | Where-Object { $_.Name -like "$n-*" })) { Fail "the wheelhouse has no $n wheel." }
}
Write-Host "wheelhouse: $Wheelhouse ($($snap.Count + 1) wheels)"

# ---- conda ----------------------------------------------------------------------------------------------------
Step "conda env '$EnvName' (Python 3.11)"
$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda -and $env:CONDA_EXE) { $conda = $env:CONDA_EXE } elseif ($conda) { $conda = $conda.Source }
if (-not $conda) { Fail "conda not found. Install Miniconda / Anaconda, open 'Anaconda Prompt' (or add conda to PATH) and run again." }
$envs = & $conda env list --json | ConvertFrom-Json
$envPath = $envs.envs | Where-Object { (Split-Path -Leaf $_) -eq $EnvName } | Select-Object -First 1
if (-not $envPath) {
    & $conda create -n $EnvName python=3.11 -y
    if ($LASTEXITCODE -ne 0) { Fail "conda create failed." }
    $envs = & $conda env list --json | ConvertFrom-Json
    $envPath = $envs.envs | Where-Object { (Split-Path -Leaf $_) -eq $EnvName } | Select-Object -First 1
} else {
    Write-Host "using the existing env $envPath"
}
$py = Join-Path $envPath "python.exe"
if (-not (Test-Path $py)) { Fail "no python.exe in $envPath" }
$ver = & $py -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($ver -ne "3.11") { Fail "env '$EnvName' runs Python $ver, the tested version is 3.11. Use another -EnvName or remove the env." }

function Pip([string[]]$pipArgs) {
    & $py -m pip @pipArgs
    if ($LASTEXITCODE -ne 0) { Fail "pip $($pipArgs -join ' ') failed (exit $LASTEXITCODE)." }
}

# ---- packages -------------------------------------------------------------------------------------------------
Step "pip"
Pip @("install", "--upgrade", "pip")
if (-not $SkipTorch) {
    Step "torch $TorchVersion (CPU build)"
    Pip @("install", "torch==$TorchVersion", "--index-url", "https://download.pytorch.org/whl/cpu")
}
Step "pinned PyPI packages (requirements\sim-pc.txt)"
Pip @("install", "-r", $Req)
Step "upstream snapshots from the wheelhouse"
Pip (@("install") + ($snap | ForEach-Object { $_.FullName }))
Step "quantcore-circuits[all]"
Pip @("install", "$($own[0].FullName)[all]")

# ---- the tests during install ---------------------------------------------------------------------------------
Step "qcc selftest"
& $py -m quantcore_circuits.cli selftest
if ($LASTEXITCODE -ne 0) { Fail "qcc selftest failed: read the FAIL lines above (a missing extra, or a broken wheel)." }

$tests = Join-Path $Root "tests"
if ((Test-Path $tests) -and (Test-Path (Join-Path $Root "pyproject.toml")) -and -not $SkipTests) {
    Step "pytest -m 'not slow' (repository checkout)"
    Push-Location $Root
    try {
        & $py -m pytest -m "not slow" -q -x
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    if ($code -ne 0) {
        Fail "pytest failed. Tests that need git-ignored folders (other-libs\, components\) fail on a fresh clone: read the first failure."
    }
} else {
    Write-Host ""
    Write-Host "(no repository checkout here, or -SkipTests: pytest not run; clone the repo and run: $py -m pytest -m `"not slow`")"
}

Write-Host ""
Write-Host "INSTALL OK. Use it with:  conda activate $EnvName   then   qcc --help" -ForegroundColor Green
Write-Host "Next: run the design notebooks one by one (docs: overview/simulation-pc)."
