<#
.SYNOPSIS
  Build the standalone Whisper Dictate bundle for Windows.

.DESCRIPTION
  Freezes the app with PyInstaller into dist\WhisperDictate\ (onedir, not
  onefile: a onefile build unpacks ~1.5 GB of torch on every launch and
  Defender re-scans it each time).

  Signing is deliberately honest:

    * An UNSIGNED build is a valid development artifact. SmartScreen shows
      "Windows protected your PC" until enough people install it; users can
      still run it via More info > Run anyway.
    * A SELF-SIGNED build is NOT a release. It only verifies on machines that
      trust the certificate, which is not a public download. The script says so
      and labels the zip accordingly.
    * A RELEASE build needs a trusted Authenticode certificate: either an OV/EV
      code-signing certificate in the user's certificate store, or Azure Trusted
      Signing / a cloud HSM signature. Windows Developer Mode is not involved in
      any of this (that setting is only for symlinks and sideloading
      development UWP/MSIX packages) - an unpacked desktop app never needs it.

.PARAMETER Sign
  Sign the executable(s) with a certificate found in CurrentUser\My.

.PARAMETER Thumbprint
  Certificate thumbprint to sign with. Defaults to the best code-signing
  certificate in CurrentUser\My.

.PARAMETER Release
  Fail instead of producing an unsigned/self-signed artifact. Use for a build
  whose zip goes on the website.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -Sign
  powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -Sign -Release
#>
[CmdletBinding()]
param(
    [switch]$Sign,
    [switch]$Release,
    [string]$Thumbprint = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$BaseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir = Join-Path $BaseDir "dist"
$Spec = Join-Path $BaseDir "packaging\whisper_dictate.spec"
$WorkDir = Join-Path $BaseDir "build\whisper-dictate"
$Version = "1.1.0"
$OutDir = Join-Path $DistDir "WhisperDictate"
$ExePath = Join-Path $OutDir "Whisper Dictate.exe"

if (-not $PythonExe) {
    $VenvPython = Join-Path $BaseDir ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) { $PythonExe = $VenvPython } else { $PythonExe = "python" }
}

Write-Host "==> Interpreter: $PythonExe"
& $PythonExe -c "import sys; print(sys.version)"

# PyInstaller (install into the venv on first use).
& $PythonExe -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Installing PyInstaller"
    & $PythonExe -m pip install --quiet "pyinstaller>=6.16"
    if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller" }
}

Write-Host "==> Freezing the app (several minutes)"
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
& $PythonExe -m PyInstaller `
    --noconfirm --clean `
    --distpath $DistDir `
    --workpath $WorkDir `
    $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
if (-not (Test-Path $ExePath)) { throw "Expected $ExePath" }

# Remove the leftover onedir folder name mismatch: PyInstaller names the folder
# WhisperDictate but the executable carries the display name.
Get-ChildItem $OutDir | ForEach-Object { Write-Host "    $($_.Name)" }

Write-Host "==> Self-check"
& $ExePath --doctor
$doctorExit = $LASTEXITCODE

# --- signing ------------------------------------------------------------------

$signStatus = "unsigned"
$cert = $null

if ($Sign) {
    if ($Thumbprint) {
        $cert = Get-Item "Cert:\CurrentUser\My\$Thumbprint" -ErrorAction SilentlyContinue
    } else {
        $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
            Where-Object { $_.NotAfter -gt (Get-Date) } |
            Sort-Object -Property @{Expression = { $_.NotAfter }} -Descending |
            Select-Object -First 1
    }
    if (-not $cert) {
        Write-Warning "No code-signing certificate found in Cert:\CurrentUser\My"
    }
}

if ($cert) {
    Write-Host "==> Signing with: $($cert.Subject) [$($cert.Thumbprint)]"
    $result = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $cert `
        -TimestampServer "http://timestamp.digicert.com" -HashAlgorithm SHA256
    Write-Host "    Status: $($result.Status)"

    $trusted = Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\TrustedPublisher `
        -ErrorAction SilentlyContinue | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }

    if ($result.Status -ne "Valid") {
        $signStatus = "invalid"
        Write-Warning "Signature did not verify: $($result.StatusMessage)"
    } elseif (-not $trusted) {
        $signStatus = "self-signed"
        Write-Warning ("The signing certificate is not in the machine's trusted " +
            "store: the signature only verifies on machines that trust it.")
    } else {
        $signStatus = "trusted"
        Write-Host "==> Trusted Authenticode signature verified"
    }
}

if ($Release -and $signStatus -ne "trusted") {
    # A zip that claims to be a release must carry a signature Windows trusts.
    # Affirmative failure: no artifact, no download page entry, and no claim.
    Write-Error @"
Refusing to produce a RELEASE build: the executable is '$signStatus'.
A public download needs a trusted Authenticode signature. Options:
  1. Buy/obtain an OV or EV code-signing certificate and import it into
     Cert:\CurrentUser\My (then run with -Sign -Release).
  2. Sign in the cloud with Azure Trusted Signing (trusted immediately,
     no HSM to ship) - sign after this script produces the bundle.
  3. Publish the bundle as a clearly-labelled unsigned preview and tell users
     about the SmartScreen prompt.
"@
    exit 3
}

# --- zip ----------------------------------------------------------------------

$suffix = switch ($signStatus) {
    "trusted" { "win64" }
    "self-signed" { "win64-selfsigned" }
    "invalid" { "win64-unsigned" }
    default { "win64-unsigned" }
}
$Zip = Join-Path $DistDir "WhisperDictate-$Version-$suffix.zip"
Remove-Item $Zip -ErrorAction SilentlyContinue
Write-Host "==> Zipping"
Compress-Archive -Path $OutDir -DestinationPath $Zip -CompressionLevel Optimal
$hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$Zip.sha256" -Value $hash -NoNewline

Write-Host ""
Write-Host "Built:  $ExePath"
Write-Host "Zip:    $Zip"
Write-Host "SHA256: $hash"
Write-Host "Sign:   $signStatus"
if ($signStatus -ne "trusted") {
    Write-Host ""
    Write-Host "This artifact is NOT signed by a trusted certificate. Do not present it"
    Write-Host "as a signed release; SmartScreen will warn until it earns reputation."
}
if ($doctorExit -ne 0) {
    Write-Warning "The frozen app's --doctor self-check reported problems."
    exit 1
}
