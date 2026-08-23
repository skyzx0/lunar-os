<#
.SYNOPSIS
    Lunar OS build driver for Windows.

.DESCRIPTION
    Windows cannot build this natively. mkarchiso needs pacstrap, bind mounts
    and a chroot, and the target rootfs needs a case-sensitive filesystem that
    carries Unix ownership. Everything runs in an x86_64 Arch container on the
    WSL2 backend; Windows only holds the source, the finished ISO and your key.

.PARAMETER Command
    doctor   check the toolchain and report what is missing
    genkey   create the repository signing key and wire it in
    image    build the Arch build container
    check    lint and sanity-check without building anything
    repo     build and sign the package repository
    iso      build the live/install ISO into out\
    test     boot the ISO in QEMU with UEFI firmware
    shell    interactive shell inside the build container
    clean    drop the build volume and out\

.EXAMPLE
    .\build\win.ps1 doctor
    .\build\win.ps1 iso
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('doctor', 'genkey', 'image', 'check', 'repo', 'iso', 'test', 'shell', 'clean')]
    [string]$Command = 'doctor'
)

$ErrorActionPreference = 'Stop'

$Root   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Image  = 'lunar-build'
$Volume = 'lunar-build-vol'
$Out    = Join-Path $Root 'out'

function Write-Step { param($m) Write-Host "`n:: $m" -ForegroundColor Cyan }
function Write-Warn { param($m) Write-Host "`n!! $m" -ForegroundColor Yellow }
function Die        { param($m) Write-Host "`n!! $m" -ForegroundColor Red; exit 1 }

function Test-Command { param($n) $null -ne (Get-Command $n -ErrorAction SilentlyContinue) }

function Assert-Docker {
    # Three distinct failures that all look the same from Get-Command:
    # not installed, installed but not on PATH, installed but engine stopped.
    # Docker Desktop only adds its bin directory to PATH after its first
    # launch, and PowerShell captures PATH at start, so "not found" is far
    # more often a stale session than a missing install.
    if (-not (Test-Command docker)) {
        $candidates = @(
            "$env:ProgramFiles\Docker\Docker\resources\bin"
            "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin"
            "$env:LOCALAPPDATA\Programs\Docker\Docker\resources\bin"
        )
        $found = $candidates | Where-Object { Test-Path (Join-Path $_ 'docker.exe') } |
                 Select-Object -First 1
        if ($found) {
            Write-Warn "docker.exe found at $found but not on this shell's PATH.
   Using it for this run. Open a new PowerShell window to pick it up
   permanently, or run:
     setx PATH `"`$env:Path;$found`""
            $env:Path = "$env:Path;$found"
        } else {
            Die @"
Docker Desktop is not installed, or was installed somewhere unexpected.

    winget install Docker.DockerDesktop

If winget says it is already installed, launch Docker Desktop from the Start
menu once - it does not register its CLI until first run - then open a NEW
PowerShell window.
"@
        }
    }

    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Die @"
The Docker CLI works but the engine is not responding.

Launch Docker Desktop from the Start menu and wait for the whale icon to
report "Engine running". First launch asks for an EULA and may want a reboot.

If it is already running, check Settings > General > Use the WSL 2 based
engine is enabled.
"@
    }
}

function Get-HostArch { $env:PROCESSOR_ARCHITECTURE }

# --------------------------------------------------------------------------

function Invoke-Doctor {
    Write-Step 'Host'
    $os = Get-CimInstance Win32_OperatingSystem
    "   {0} build {1} on {2}" -f $os.Caption, $os.BuildNumber, (Get-HostArch) | Write-Host

    if ((Get-HostArch) -eq 'ARM64') {
        Write-Warn @"
Windows on ARM. There is no Rosetta equivalent here, so x86_64 containers run
under full qemu-user emulation. An ISO build will likely take several hours and
may hit unimplemented instructions in the middle of a package build. A cheap
x86_64 Linux box, or a cloud VM for the length of the build, is the pragmatic
answer.
"@
    }

    Write-Step 'WSL'
    if (Test-Command wsl) {
        $wslVersion = (wsl --version 2>$null | Select-Object -First 1)
        if ($wslVersion) { "   $wslVersion" | Write-Host }
        else { Write-Warn "WSL is present but appears to be version 1. Run: wsl --update" }
    } else {
        Die "WSL is missing. Run in an elevated prompt:`n    wsl --install"
    }

    Write-Step 'Docker'
    Assert-Docker
    $backend = docker info --format '{{.OperatingSystem}}' 2>$null
    "   $backend" | Write-Host
    if ($backend -notmatch 'WSL|Docker Desktop') {
        Write-Warn "Not obviously on the WSL2 backend. The Hyper-V backend also
   works but is slower and its disk fills up faster."
    }

    $mem = [int64](docker info --format '{{.MemTotal}}' 2>$null)
    if ($mem -gt 0) {
        "   VM memory: {0} GiB" -f [math]::Round($mem / 1GB, 1) | Write-Host
        if ($mem -lt 6GB) {
            Write-Warn @"
mkarchiso wants at least 6 GiB. Create %USERPROFILE%\.wslconfig with:

    [wsl2]
    memory=12GB
    processors=6
    swap=8GB

then run: wsl --shutdown
"@
        }
    }

    Write-Step 'Disk'
    $drive = Get-PSDrive -Name (Split-Path -Qualifier $Root).TrimEnd(':')
    "   Free on {0}: {1} GiB" -f $drive.Name, [math]::Round($drive.Free / 1GB, 1) | Write-Host
    if ($drive.Free -lt 40GB) {
        Write-Warn "Under 40 GiB free. The container volume alone needs about 25 GiB."
    }

    Write-Step 'Line endings'
    $gitattributes = Join-Path $Root '.gitattributes'
    if (Test-Path $gitattributes) {
        "   .gitattributes present, shell scripts will stay LF" | Write-Host
    } else {
        Write-Warn "No .gitattributes. If Git converted the scripts to CRLF the
   container normalises them on copy, so builds still work, but set
   'git config core.autocrlf input' to avoid churn in diffs."
    }

    Write-Step 'Signing'
    $keyFile = Join-Path $Root 'repo\signing-key.txt'
    if (Test-Path $keyFile) {
        "   key id: {0}" -f (Get-Content $keyFile -Raw).Trim() | Write-Host
    } else {
        Write-Warn "repo\signing-key.txt missing. 'repo' and 'iso' will fail.`n   Run: .\build\win.ps1 genkey"
    }
    if (-not (Test-Command gpg)) {
        Write-Warn "gpg not found. Install with: winget install GnuPG.Gpg4win"
    }

    Write-Step 'Optional'
    if (-not (Test-Command qemu-system-x86_64)) {
        # The QEMU Windows installer does not touch PATH.
        $qemuDir = @("$env:ProgramFiles\qemu", "${env:ProgramFiles(x86)}\qemu") |
                   Where-Object { Test-Path (Join-Path $_ 'qemu-system-x86_64.exe') } |
                   Select-Object -First 1
        if ($qemuDir) {
            "   qemu at $qemuDir but not on PATH. Only 'test' needs it. Add it with:" | Write-Host
            "     setx PATH `"%PATH%;$qemuDir`"" | Write-Host
        } else {
            "   qemu missing, install with: winget install SoftwareFreedomConservancy.QEMU" | Write-Host
        }
    } else {
        "   qemu present, 'test' will work" | Write-Host
    }
}

function Invoke-GenKey {
    if (-not (Test-Command gpg)) { Die "Install GnuPG first: winget install GnuPG.Gpg4win" }

    Write-Step 'Generating a Lunar OS repository signing key'
    Write-Host @"
Answer the prompts. Recommended: RSA 4096, no expiry, a real passphrase.
This key signs every package your machines will trust with root. Back up
the keyring somewhere offline afterwards.
"@
    gpg --full-generate-key
    if ($LASTEXITCODE -ne 0) { Die "Key generation was cancelled." }

    $keyid = (gpg --list-secret-keys --with-colons |
              Select-String '^fpr:' | Select-Object -First 1) -split ':' | Select-Object -Index 9
    if (-not $keyid) { Die "Could not determine the new key id." }

    $keyringDir = Join-Path $Root 'repo\packages\lunar-keyring'
    # UTF8 without BOM: a BOM in an ASCII-armoured key breaks gpg --import.
    $enc = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText((Join-Path $keyringDir 'lunar.gpg'),
                            (gpg --export --armor $keyid | Out-String), $enc)
    [IO.File]::WriteAllText((Join-Path $Root 'repo\signing-key.txt'), "$keyid`n", $enc)
    [IO.File]::WriteAllText((Join-Path $keyringDir 'lunar-trusted'), "${keyid}:4:`n", $enc)
    [IO.File]::WriteAllText((Join-Path $keyringDir 'lunar-revoked'), '', $enc)

    Write-Step "Key $keyid recorded"
    "   repo\signing-key.txt and the keyring package are populated." | Write-Host
}

function Invoke-Image {
    Assert-Docker
    Write-Step "Building the $Image container"
    docker build --platform linux/amd64 -t $Image (Join-Path $Root 'build')
    if ($LASTEXITCODE -ne 0) { Die "Container build failed." }
}

function Confirm-Image {
    Assert-Docker
    docker image inspect $Image *> $null
    if ($LASTEXITCODE -ne 0) { Invoke-Image }
    docker volume inspect $Volume *> $null
    if ($LASTEXITCODE -ne 0) { docker volume create $Volume | Out-Null }
    New-Item -ItemType Directory -Force -Path $Out | Out-Null
}

# mkarchiso does bind mounts and pacstrap chroots, so it needs full privileges.
# The GnuPG home is mounted read-only so makepkg can sign without the private
# key ever being copied into an image layer.
function Invoke-Container {
    param([string[]]$Args)
    Confirm-Image

    $mounts = @(
        '-v', "${Root}:/src:ro"
        '-v', "${Volume}:/build"
        '-v', "${Out}:/out"
    )
    $gnupg = Join-Path $env:APPDATA 'gnupg'
    if (Test-Path $gnupg) { $mounts += @('-v', "${gnupg}:/home/builder/.gnupg:ro") }

    docker run --rm -it --platform linux/amd64 --privileged @mounts $Image @Args
    if ($LASTEXITCODE -ne 0) { Die "Build failed inside the container." }
}

function Invoke-Test {
    if (-not (Test-Command qemu-system-x86_64)) {
        $qemuDir = @("$env:ProgramFiles\qemu", "${env:ProgramFiles(x86)}\qemu") |
                   Where-Object { Test-Path (Join-Path $_ 'qemu-system-x86_64.exe') } |
                   Select-Object -First 1
        if ($qemuDir) {
            $env:Path = "$env:Path;$qemuDir"
        } else {
            Die "Install QEMU: winget install SoftwareFreedomConservancy.QEMU"
        }
    }
    $iso = Get-ChildItem (Join-Path $Out '*.iso') -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $iso) { Die "No ISO in out\. Run: .\build\win.ps1 iso" }

    $qemuDir = Split-Path (Get-Command qemu-system-x86_64).Source
    $fwCode  = Join-Path $qemuDir 'share\edk2-x86_64-code.fd'
    if (-not (Test-Path $fwCode)) { $fwCode = Join-Path $qemuDir 'edk2-x86_64-code.fd' }
    if (-not (Test-Path $fwCode)) { Die "UEFI firmware not found next to qemu. Reinstall QEMU." }

    $fwVars = Join-Path $Out 'OVMF_VARS.fd'
    if (-not (Test-Path $fwVars)) { qemu-img create -f raw $fwVars 4M | Out-Null }
    $disk = Join-Path $Out 'test.qcow2'
    if (-not (Test-Path $disk)) { qemu-img create -f qcow2 $disk 40G | Out-Null }

    Write-Step "Booting $($iso.Name)"
    $accel = if ((Get-HostArch) -eq 'AMD64') { 'whpx,kernel-irqchip=off' } else { 'tcg' }
    if ($accel -eq 'tcg') {
        Write-Warn "No hardware acceleration on this architecture. The guest will crawl."
    }

    qemu-system-x86_64 `
        -machine q35 -accel $accel -m 4096 -smp 4 `
        -drive "if=pflash,format=raw,readonly=on,file=$fwCode" `
        -drive "if=pflash,format=raw,file=$fwVars" `
        -drive "file=$disk,if=virtio,format=qcow2" `
        -cdrom $iso.FullName -boot d `
        -device virtio-net-pci,netdev=n0 -netdev user,id=n0
}

function Invoke-Clean {
    Assert-Docker
    docker volume rm -f $Volume *> $null
    if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
    Write-Step 'Removed the build volume and out\'
}

switch ($Command) {
    'doctor' { Invoke-Doctor }
    'genkey' { Invoke-GenKey }
    'image'  { Invoke-Image }
    'check'  { Invoke-Container @('check') }
    'repo'   { Invoke-Container @('repo') }
    'iso'    { Invoke-Container @('repo'); Invoke-Container @('iso') }
    'shell'  { Invoke-Container @('shell') }
    'test'   { Invoke-Test }
    'clean'  { Invoke-Clean }
}
