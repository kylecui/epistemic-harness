# hvx.ps1 — harness verify, interpreter-independent (Windows).
# Resolves the project interpreter without assuming anything about PATH:
#   1. .venv (created by scripts/install.py)
#   2. py launcher
#   3. python on PATH
$Root = Split-Path $PSScriptRoot -Parent
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) { $Py = $VenvPy }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $Py = "py" ; $ArgsPrefix = @("-3") }
else { $Py = "python" }
& $Py @ArgsPrefix "$Root\scripts\verify.py" @args
exit $LASTEXITCODE
