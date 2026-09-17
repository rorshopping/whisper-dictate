<#
  Build Whisper Dictate on Windows, over SSH, end to end.

  This is the Windows counterpart to scripts/build_release.sh and
  scripts/build_release_linux.sh. It lives in the repository so the process is
  reviewable, but note the path assumptions at the top: the sources are copied
  into C:\Users\Richard\whisper-build (that machine's git checkout cannot
  authenticate to GitHub), and the venv is created fresh so the developer's
  CUDA torch install is not packaged.

  Why CPU-only torch: the CUDA wheel is 4 GB plus a 2 GB NVIDIA runtime. The
  Nemotron models are 0.6B parameters and load in ~2 s on the CPU, so the
  download stays ~370 MB instead of ~5 GB. A GPU user can install the CUDA
  wheel afterwards; the app reports the CPU fallback in its log rather than
  failing.

  There is no code-signing certificate on this machine, so the artifact is
  named "-unsigned" and never presented as signed. See docs/BUILD_MACHINES.md.
#>
$ErrorActionPreference = "Stop"

$Src = "C:\Users\Richard\whisper-build"
$VenvDir = "C:\Users\Richard\whisper-venv"
$Py = "C:\Users\Richard\AppData\Local\Programs\Python\Python312\python.exe"
$VenvPy = "$VenvDir\Scripts\python.exe"
$Version = "1.1.0"

Write-Output "=== 0. sanity ==="
& $Py --version
if (-not (Test-Path "$Src\packaging\whisper_dictate.spec")) {
    throw "no sources at $Src - copy them with the tar/scp recipe in docs/BUILD_MACHINES.md"
}

Write-Output ""
Write-Output "=== 1. clean venv (python 3.12) ==="
if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
& $Py -m venv $VenvDir
& $VenvPy --version

Write-Output ""
Write-Output "=== 2. pip install (CPU torch) ==="
& $VenvPy -m pip install --quiet --upgrade pip
& $VenvPy -m pip install --quiet -r "$Src\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }

Write-Output ""
Write-Output "=== 3. build tools ==="
& $VenvPy -m pip install --quiet "pyinstaller>=6.16" rapidfuzz
if ($LASTEXITCODE -ne 0) { throw "build tool install failed" }

Write-Output ""
Write-Output "=== 4. dependency check ==="
& $VenvPy -c "import torch,transformers,librosa,faster_whisper,ctranslate2,PyInstaller;print('torch',torch.__version__,'cuda',torch.cuda.is_available());print('transformers',transformers.__version__);print('librosa',librosa.__version__);print('pyinstaller',PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) { throw "a required dependency is missing" }

Write-Output ""
Write-Output "=== 5. syntax check and unit tests ==="
Push-Location $Src
& $VenvPy -m py_compile main.py enhanced_features.py desktop_ui.py history_store.py text_tools.py app_paths.py launcher.py
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "the app does not compile" }
# The publisher regression suite exercises a POSIX shell and executable
# shebang stubs; run it on macOS/Linux, not native Windows. Run every native
# application suite here (including the shared-history-lock regressions).
& $VenvPy -m unittest tests.test_app_paths tests.test_history_store tests.test_text_tools
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "unit tests failed on Windows" }
Pop-Location

Write-Output ""
Write-Output "=== 6. freeze (PyInstaller) ==="
Push-Location $Src
& $VenvPy -m PyInstaller --noconfirm --clean --distpath "$Src\dist" --workpath "$Src\build\w" "$Src\packaging\whisper_dictate.spec"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "PyInstaller failed" }
Pop-Location

$OutDir = "$Src\dist\WhisperDictate"
$Exe = "$OutDir\Whisper Dictate.exe"
if (-not (Test-Path $Exe)) { throw "no executable at $Exe" }

Write-Output ""
Write-Output "=== 7. bundle size ==="
[math]::Round((Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 0)
Get-ChildItem $OutDir | Select-Object -ExpandProperty Name | Select-Object -First 8

Write-Output ""
Write-Output "=== 8. doctor self-check ==="
$report = "$env:APPDATA\Whisper Dictate\doctor-report.txt"
Remove-Item $report -ErrorAction SilentlyContinue
$p = Start-Process -FilePath $Exe -ArgumentList "--doctor" -PassThru -WindowStyle Hidden
if (-not $p.WaitForExit(240000)) {
    $p.Kill()
    throw "doctor timed out - refusing to package"
}
$p.Refresh()
if (-not (Test-Path $report)) { throw "doctor produced no report - refusing to package" }
$doctorReport = Get-Content $report -Raw
Write-Output $doctorReport
if ($p.ExitCode -ne 0 -or $doctorReport -match '\[FAIL\]' -or
    $doctorReport -notmatch '\d+/\d+ checks passed\.') {
    throw "doctor failed (exit $($p.ExitCode)) - refusing to package"
}

Write-Output ""
Write-Output "=== 8b. model load check ==="
# --doctor only imports modules; it cannot catch a missing dependency inside a
# lazily-imported library. The macOS build shipped once without librosa and
# failed at model load, so the frozen app is actually started here and its log
# is checked. The app falls back to the CPU when torch has no CUDA device, which
# is expected for this CPU-only build.
$log = "$env:APPDATA\Whisper Dictate\dictate.log"
Remove-Item $log -ErrorAction SilentlyContinue
$app = Start-Process -FilePath $Exe -PassThru
$loaded = $false
for ($i = 0; $i -lt 150; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $content = Get-Content $log -Raw -ErrorAction SilentlyContinue
        if ($content -match "ready on|Model loaded") { $loaded = $true; break }
        if ($content -match "requires the librosa library|Preload of default model failed") { break }
    }
    if ($app.HasExited) { break }
}
if (-not $app.HasExited) { Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue }
if ($loaded) {
    Get-Content $log | Select-String -Pattern "ready on|Model loaded" | Select-Object -First 2
    Write-Output "    model loaded"
} else {
    Write-Output "ERROR: the frozen app did not load its model:"
    Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 10
    throw "model load check failed - this build is broken, do not publish it"
}

Write-Output ""
Write-Output "=== 9. signature ==="
$sig = Get-AuthenticodeSignature $Exe
Write-Output "status: $($sig.Status)"

Write-Output ""
Write-Output "=== 10. zip ==="
$zip = "$Src\dist\WhisperDictate-$Version-win64-unsigned.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $OutDir -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Set-Content "$zip.sha256" $hash -NoNewline
Write-Output "zip:    $zip"
Write-Output "sha256: $hash"
[math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Output "=== DONE ==="
