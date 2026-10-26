# Join the Lunar OS Live pieces into one ISO, using as little space as
# possible: each piece is deleted as soon as it has been added.
$ErrorActionPreference = 'Stop'
$dl = "$env:USERPROFILE\Downloads"
$parts = "$dl\lunaros-live-parts"
try {
    # Nothing is deleted except the Live pieces themselves, one by one as
    # they are joined. Your other ISOs are never touched.
    $pieces = Get-ChildItem "$parts\live-*.bin" -ErrorAction SilentlyContinue | Sort-Object Name
    if (-not $pieces) { throw "The Live ISO has not arrived yet - nothing was changed. Wait until Claude says it is ready." }
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
