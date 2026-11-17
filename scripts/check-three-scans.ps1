<#
.SYNOPSIS
  Processes a scanned PDF three times at once, several times over, with an installed PDF Remediator, and reports how many runs finished.

.DESCRIPTION
  Used before a release, on a fresh install: scanned-page OCR must not fail at random (alpha 8 and alpha 9 failed about 2 runs in 9 under this load).
  It starts a second copy of the installed program's own service on a temporary data folder, so the person's saved reviews are not touched, uploads
  the PDF once per run, starts three runs at the same time with the "OCR: scan-only page" option, waits for them, counts the results, stops the service
  and deletes the temporary folder. Nothing is sent over the internet. Exit code 0 means every run finished (no "OCR did not complete"); 1 means at least
  one failed or did not finish; 2 means it could not start.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\check-three-scans.ps1 -Pdf C:\scans\six-page-scan.pdf -Rounds 4
  powershell -ExecutionPolicy Bypass -File check-three-scans.ps1 -Pdf D:\scan.pdf -InstallFolder "D:\Apps\PDF Remediator"
#>
param(
  [Parameter(Mandatory = $true)][string]$Pdf,
  [string]$InstallFolder = (Join-Path $env:LOCALAPPDATA 'PDF Remediator'),
  [int]$Rounds = 4,
  [int]$Port = 53910
)
$ErrorActionPreference = 'Stop'
function Stop-With($code, $message) { Write-Host $message; exit $code }
if (-not (Test-Path -LiteralPath $Pdf)) { Stop-With 2 "The PDF was not found: $Pdf" }
$python = Join-Path $InstallFolder 'runtime\python\python.exe'
$config = Join-Path $InstallFolder 'local-runtime.toml'
if (-not (Test-Path $python) -or -not (Test-Path $config)) { Stop-With 2 "No installed copy of PDF Remediator was found in: $InstallFolder" }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { Stop-With 2 "Port $Port is in use; pass another one with -Port." }

$release = (Get-Content (Join-Path $InstallFolder 'package-manifest.json') -Raw | ConvertFrom-Json).release
Write-Host "Installed release: $release"
$temp = Join-Path ([IO.Path]::GetTempPath()) ('pdfr-three-scans-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory (Join-Path $temp 'data') | Out-Null
$quote = { param($s) '"' + $s + '"' }
$arguments = @('-m', 'pdf_remediator', 'serve', '--data-dir', (& $quote (Join-Path $temp 'data')), '--no-open',
               '--session-file', (& $quote (Join-Path $temp 'session.json')), '--config', (& $quote $config), '--port', "$Port")
$service = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $InstallFolder -PassThru -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $temp 'out.log') -RedirectStandardError (Join-Path $temp 'err.log')
$origin = $null; $token = $null
try {
  for ($i = 0; $i -lt 40 -and -not $origin; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path (Join-Path $temp 'session.json')) { $s = Get-Content (Join-Path $temp 'session.json') -Raw | ConvertFrom-Json; $origin = $s.origin; $token = $s.url.Split('#')[1] }
  }
  if (-not $origin) { Stop-With 2 'The service did not start.' }
  $headers = @{ 'X-Review-Token' = $token }
  $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Pdf))
  $options = @{ ocr_mode = 'skip'; ocr_profile = 'standard'; language = 'en-US'; document_kind = 'unknown' }
  $total = 0; $notFinished = 0; $failedReasons = @()
  foreach ($round in 1..$Rounds) {
    $ids = @()
    foreach ($i in 1..3) {
      $name = "three-scans-$round-$i.pdf"
      $upload = Invoke-RestMethod -Method Post -Uri "$origin/api/upload" -Headers (@{ 'X-Review-Token' = $token; 'X-File-Name' = $name }) -ContentType 'application/pdf' -Body $bytes
      $ids += $upload.id
    }
    # Three separate runs started back to back, so they overlap.
    $jobs = foreach ($id in $ids) {
      (Invoke-RestMethod -Method Post -Uri "$origin/api/process" -Headers $headers -ContentType 'application/json' -Body (@{ inputs = @($id); options = $options } | ConvertTo-Json -Depth 4)).job_id
    }
    $deadline = (Get-Date).AddMinutes(10)
    do {
      Start-Sleep -Seconds 5
      $dashboard = Invoke-RestMethod -Uri "$origin/api/dashboard" -Headers $headers
      $running = @($dashboard.jobs | Where-Object { $_.id -in $jobs -and $_.status -notin 'done', 'failed', 'error', 'cancelled' }).Count
    } while ($running -gt 0 -and (Get-Date) -lt $deadline)
    $documents = @($dashboard.documents | Where-Object { $_.title -like "three-scans-$round-*" })
    $total += 3
    $notFinished += (3 - $documents.Count) + @($dashboard.jobs | Where-Object { $_.id -in $jobs -and $_.status -ne 'done' }).Count
    foreach ($document in ($documents | Where-Object { $_.status -eq 'failed' })) {
      $view = Invoke-RestMethod -Uri "$origin/api/workspaces/$($document.id)" -Headers $headers
      $failedReasons += "round $round, $($document.title): " + (($view.blockers | ForEach-Object { $_.description }) -join '; ')
    }
    $summary = ($documents | Group-Object status | ForEach-Object { "$($_.Count) $($_.Name)" }) -join ', '
    Write-Host "Round $round (three at once): $summary"
  }
  $all = Invoke-RestMethod -Uri "$origin/api/dashboard" -Headers $headers
  $failed = @($all.documents | Where-Object { $_.status -eq 'failed' }).Count
  Write-Host ''
  Write-Host "Runs: $total | failed: $failed | did not finish: $notFinished"
  $failedReasons | ForEach-Object { Write-Host "  $_" }
  if ($failed -eq 0 -and $notFinished -eq 0) { Write-Host 'PASS: every run finished.'; $code = 0 } else { Write-Host 'FAIL: at least one run did not finish.'; $code = 1 }
}
finally {
  if ($origin) { try { Invoke-RestMethod -Method Post -Uri "$origin/api/stop" -Headers @{ 'X-Review-Token' = $token } -ContentType 'application/json' -Body '{}' | Out-Null } catch { } }
  Start-Sleep -Seconds 3
  if ($service -and -not $service.HasExited) { Stop-Process -Id $service.Id -Force -ErrorAction SilentlyContinue }
  Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}
exit $code
