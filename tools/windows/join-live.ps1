# Join the Lunar OS Live pieces into one ISO, using as little space as
# possible: each piece is deleted as soon as it has been added. Also clears
# out the older Lunar OS downloads to make room.
$ErrorActionPreference = 'Stop'
$dl = "$env:USERPROFILE\Downloads"
$parts = "$dl\lunaros-live-parts"
try {
    Write-Host "Removing older Lunar OS downloads to free space..." -ForegroundColor Cyan
    foreach ($old in @("$dl\lunaros-parts", "$dl\lunaros-2026.10.25-x86_64.iso", "$dl\lunar-os-step27.tar.gz")) {
        if (Test-Path $old) { Remove-Item -Recurse -Force $old; Write-Host "  removed $old" }
    }
    $pieces = Get-ChildItem "$parts\live-*.bin" | Sort-Object Name
    if (-not $pieces) { throw "No pieces found in $parts" }
    $iso = "$dl\lunaros-live.iso"
    Write-Host "Joining $($pieces.Count) pieces into lunaros-live.iso..." -ForegroundColor Cyan
    $out = [IO.File]::Open($iso, 'Create', 'Write')
    try {
        $i = 0
        foreach ($p in $pieces) {
            $in = [IO.File]::OpenRead($p.FullName)
            $in.CopyTo($out); $in.Close()
            Remove-Item $p.FullName
            $i++; Write-Progress -Activity "Joining" -PercentComplete ($i * 100 / $pieces.Count)
        }
    } finally { $out.Close() }
    $want = (Get-Content "$parts\SHA256SUMS.txt" -ErrorAction SilentlyContinue | Select-Object -First 1) -split '\s+' | Select-Object -First 1
    Write-Host "Checking..." -ForegroundColor Cyan
    $got = (Get-FileHash $iso -Algorithm SHA256).Hash.ToLower()
    if ($want -and $got -ne $want) { throw "The joined ISO does not match (got $got)" }
    Remove-Item -Recurse -Force $parts
    Write-Host "Done: $iso - checksum matches." -ForegroundColor Green
    Write-Host "Now double-click lunar-vm.cmd in Downloads."
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}
Read-Host "Press Enter to close"
