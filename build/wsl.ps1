<#
.SYNOPSIS
    Lunar OS build driver using WSL2 directly, with no Docker Desktop.

.DESCRIPTION
    WSL2 runs a real Linux kernel with loop device and chroot support, which is
    everything mkarchiso needs. This path installs an Arch distribution into
    WSL and builds there. Fewer moving parts than the Docker path and a lot
    less disk overhead, at the cost of being less isolated: the build tooling
    lives in a distro you keep around rather than a container you throw away.

    Windows still cannot build this natively. The Arch userspace has to exist
    somewhere; this puts it in WSL instead of a container.

.PARAMETER Command
    doctor   check WSL, disk space and whether the Arch distro is ready
    setup    install the Arch distro and its build dependencies
    sync     copy the project into the distro's ext4 filesystem
    repo     build and sign the package repository
    iso      build the ISO and copy it back to out\
    shell    drop into a shell inside the build distro
    move     relocate the distro to another drive
    clean    remove the build distro entirely

.EXAMPLE
    .\build\wsl.ps1 doctor
    .\build\wsl.ps1 setup
    .\build\wsl.ps1 iso
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('doctor', 'setup', 'sync', 'repo', 'iso', 'shell', 'move', 'clean')]
    [string]$Command = 'doctor',

    [Parameter(Position = 1)]
    [string]$Target
)

$ErrorActionPreference = 'Stop'

$Root   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Distro = 'lunar-build'
$Out    = Join-Path $Root 'out'
$WorkIn = '/root/lunar-os'          # inside the distro, on ext4

function Write-Step { param($m) Write-Host "`n:: $m" -ForegroundColor Cyan }
function Write-Warn { param($m) Write-Host "`n!! $m" -ForegroundColor Yellow }
function Die        { param($m) Write-Host "`n!! $m" -ForegroundColor Red; exit 1 }

function Test-Distro {
    # wsl.exe emits UTF-16; -Raw plus a null strip keeps the match reliable.
    $list = (wsl.exe -l -q | Out-String) -replace "`0", ''
    $list -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -eq $Distro }
}

function Invoke-Wsl {
    param([string]$Cmd, [switch]$AsUser)
    wsl.exe -d $Distro --cd /root -- bash -lc $Cmd
    if ($LASTEXITCODE -ne 0) { Die "Command failed inside $Distro." }
}

function Get-FreeGB {
    param($Path)
    $q = (Split-Path -Qualifier $Path).TrimEnd(':')
    [math]::Round((Get-PSDrive -Name $q).Free / 1GB, 1)
}

# --------------------------------------------------------------------------

function Invoke-Doctor {
    Write-Step 'WSL'
    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
        Die "WSL is not installed. Run in an elevated prompt: wsl --install"
    }
    $ver = (wsl.exe --version 2>$null | Out-String) -replace "`0", ''
    ($ver -split "`r?`n" | Select-Object -First 1) | Write-Host

    Write-Step 'Build distro'
    if (Test-Distro) {
        Write-Host "   $Distro is installed"
        $has = wsl.exe -d $Distro -- bash -lc 'command -v mkarchiso >/dev/null && echo yes'
        if (($has | Out-String).Trim() -eq 'yes') {
            Write-Host '   archiso present, ready to build'
        } else {
            Write-Warn "Dependencies not installed. Run: .\build\wsl.ps1 setup"
        }
    } else {
        Write-Warn "$Distro not found. Run: .\build\wsl.ps1 setup"
    }

    Write-Step 'Disk'
    # This is the constraint that actually stops builds.
    $vhdxDrive = 'C'
    $free = Get-FreeGB "${vhdxDrive}:\"
    Write-Host "   Free on ${vhdxDrive}: $free GiB"
    if ($free -lt 40) {
        Write-Warn @"
Under 40 GiB free. The build needs roughly:

    Arch base + build tooling      3 GiB
    downloaded packages            4 GiB
    mkarchiso work directory      20 GiB
    finished ISO                   3 GiB

WSL stores its ext4 disk on C: by default. If another drive has room, move the
build distro there once it exists:

    .\build\wsl.ps1 move D:\wsl

Otherwise free space on C: first. The build will fail partway through and leave
a 20 GiB work directory behind if you start it short on space.
"@
    }

    Write-Step 'Signing'
    if (Test-Path (Join-Path $Root 'repo\signing-key.txt')) {
        "   key id: {0}" -f (Get-Content (Join-Path $Root 'repo\signing-key.txt') -Raw).Trim() |
            Write-Host
    } else {
        Write-Warn "repo\signing-key.txt missing. 'setup' will generate a key inside
   the build distro, or create one on Windows with build\win.ps1 genkey."
    }
}

function Invoke-Setup {
    if (Test-Distro) {
        Write-Step "$Distro already exists, installing dependencies only"
    } else {
        Write-Step 'Installing the Arch distribution into WSL'
        Write-Host '   This downloads roughly 300 MB.'
        wsl.exe --install archlinux --name $Distro --no-launch
        if ($LASTEXITCODE -ne 0) {
            Die @"
Could not install the archlinux distro. Check what your WSL offers:

    wsl --list --online

If archlinux is not listed, update WSL first:

    wsl --update
"@
        }
    }

    Write-Step 'Installing build dependencies'
    $script = (Get-Content (Join-Path $Root 'build\wsl-setup.sh') -Raw) -replace "`r", ''
    $tmp = [IO.Path]::GetTempFileName()
    [IO.File]::WriteAllText($tmp, $script, (New-Object System.Text.UTF8Encoding $false))
    $wslPath = (wsl.exe -d $Distro -- wslpath -a ($tmp -replace '\\', '/') | Out-String).Trim()
    wsl.exe -d $Distro -u root -- bash $wslPath
    if ($LASTEXITCODE -ne 0) { Die 'Dependency installation failed.' }
    Remove-Item $tmp -Force

    Write-Step 'Ready'
    Write-Host '   Next: .\build\wsl.ps1 iso'
}

function Invoke-Sync {
    if (-not (Test-Distro)) { Die "Run .\build\wsl.ps1 setup first." }
    Write-Step 'Copying the project into the distro'
    # Building on /mnt/c is slow and reintroduces every permission and
    # case-sensitivity problem the container path exists to avoid, so the
    # source is copied onto ext4 first.
    $src = (wsl.exe -d $Distro -- wslpath -a ($Root -replace '\\', '/') | Out-String).Trim()
    Invoke-Wsl "mkdir -p $WorkIn && rsync -a --delete --exclude out/ --exclude work/ --exclude '__pycache__/' --exclude '.git/' '$src/' '$WorkIn/'"
    # Windows line endings break shebangs and PKGBUILDs in ways that point
    # nowhere near the real cause.
    Invoke-Wsl "cd $WorkIn && grep -rlI \$'\r' . 2>/dev/null | xargs -r sed -i 's/\r`$//' ; chmod +x repo/build-repo.sh build/*.sh 2>/dev/null || true"
}

function Invoke-Repo {
    Invoke-Sync
    Write-Step 'Building packages'
    Invoke-Wsl "cd $WorkIn && sudo -u builder ./repo/build-repo.sh"
}

function Invoke-Iso {
    Invoke-Repo
    Write-Step 'Building the ISO'
    Invoke-Wsl "cd $WorkIn && rm -rf /root/work && mkarchiso -v -w /root/work -o /root/isoout archiso/lunar"

    Write-Step 'Copying the ISO back to Windows'
    New-Item -ItemType Directory -Force -Path $Out | Out-Null
    $dst = (wsl.exe -d $Distro -- wslpath -a ($Out -replace '\\', '/') | Out-String).Trim()
    Invoke-Wsl "cp /root/isoout/*.iso '$dst/' && rm -rf /root/work"
    Get-ChildItem (Join-Path $Out '*.iso') | ForEach-Object {
        "   {0}  {1} GiB" -f $_.Name, [math]::Round($_.Length / 1GB, 2) | Write-Host
    }
}

function Invoke-Move {
    if (-not $Target) { Die "Give a destination: .\build\wsl.ps1 move D:\wsl" }
    if (-not (Test-Distro)) { Die "$Distro does not exist yet." }

    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $tar = Join-Path $env:TEMP "$Distro.tar"

    Write-Step 'Exporting the distro'
    wsl.exe --shutdown
    wsl.exe --export $Distro $tar
    if ($LASTEXITCODE -ne 0) { Die 'Export failed. Nothing was changed.' }

    Write-Step 'Unregistering and re-importing at the new location'
    wsl.exe --unregister $Distro
    wsl.exe --import $Distro $Target $tar --version 2
    if ($LASTEXITCODE -ne 0) {
        Die "Re-import failed. Your data is still in the export at:`n   $tar"
    }
    Remove-Item $tar -Force
    Write-Step "Moved to $Target"
}

function Invoke-Clean {
    if (-not (Test-Distro)) { Write-Step 'Nothing to remove'; return }
    Write-Warn "This unregisters $Distro and deletes everything inside it."
    $answer = Read-Host 'Type the distro name to confirm'
    if ($answer -ne $Distro) { Die 'Cancelled.' }
    wsl.exe --unregister $Distro
    Write-Step 'Removed'
}

switch ($Command) {
    'doctor' { Invoke-Doctor }
    'setup'  { Invoke-Setup }
    'sync'   { Invoke-Sync }
    'repo'   { Invoke-Repo }
    'iso'    { Invoke-Iso }
    'shell'  { wsl.exe -d $Distro --cd $WorkIn }
    'move'   { Invoke-Move }
    'clean'  { Invoke-Clean }
}
