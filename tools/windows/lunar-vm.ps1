# Lunar OS Live in VirtualBox - no virtual disk: everything runs from the ISO
# and memory, so the VM takes a few megabytes of your drive. Changes made
# inside it are gone when it shuts down.
$ErrorActionPreference = 'Stop'
try {
    $vbox = @("$env:ProgramFiles\Oracle\VirtualBox\VBoxManage.exe",
              "${env:ProgramFiles(x86)}\Oracle\VirtualBox\VBoxManage.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $vbox) {
        Write-Host "VirtualBox is not installed. Installing it..." -ForegroundColor Cyan
        winget install --id Oracle.VirtualBox -e --accept-source-agreements --accept-package-agreements
        $vbox = "$env:ProgramFiles\Oracle\VirtualBox\VBoxManage.exe"
    }
    $iso = Get-ChildItem "$env:USERPROFILE\Downloads\lunaros-live*.iso" -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $iso) { throw "No lunaros-live ISO in Downloads yet." }
    $name = "Lunar OS Live"

    # Memory: half of this PC's, between 3 and 8 GB. Cores: half, at most 4.
    $ramMB = [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB / 2)
    $ramMB = [math]::Max(3072, [math]::Min(8192, $ramMB))
    $cpus  = [math]::Max(2, [math]::Min(4, [int]([Environment]::ProcessorCount / 2)))

    $exists = (& $vbox list vms) -match [regex]::Escape("`"$name`"")
    if (-not $exists) {
        Write-Host "Creating the VM (no virtual disk)..." -ForegroundColor Cyan
        & $vbox createvm --name $name --ostype ArchLinux_64 --register | Out-Null
        & $vbox modifyvm $name --memory $ramMB --cpus $cpus --firmware efi `
            --graphicscontroller vmsvga --vram 128 --mouse usbtablet `
            --nic1 nat --boot1 dvd --boot2 none --boot3 none --boot4 none | Out-Null
        # 3D and sound: option names differ between VirtualBox 6 and 7.
        $ErrorActionPreference = 'Continue'
        & $vbox modifyvm $name --accelerate-3d on *> $null
        if ($LASTEXITCODE) { & $vbox modifyvm $name --accelerate3d on *> $null }
        & $vbox modifyvm $name --audio-driver default --audio-enabled on --audio-out on *> $null
        if ($LASTEXITCODE) { & $vbox modifyvm $name --audio dsound --audioout on *> $null }
        $ErrorActionPreference = 'Stop'
        & $vbox storagectl $name --name SATA --add sata --controller IntelAhci --portcount 1 | Out-Null
    } else {
        & $vbox modifyvm $name --memory $ramMB --cpus $cpus | Out-Null
    }
    & $vbox storageattach $name --storagectl SATA --port 0 --device 0 --type dvddrive --medium $iso.FullName | Out-Null
    Write-Host "Starting $name from $($iso.Name) ($ramMB MB, $cpus cores)" -ForegroundColor Green
    Write-Host "It logs in to Hyprland. Log out (Super+Escape) to choose Plasma, GNOME, Sway or i3."
    Write-Host "User: lunar   Password: lunar"
    & $vbox startvm $name --type gui | Out-Null
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}
Read-Host "Press Enter to close"
