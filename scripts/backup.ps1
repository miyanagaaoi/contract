# CTMS backup script (Windows).
#   - SQLite: online-safe backup via sqlite3 backup API
#   - attachments: zip of uploads dir
#   - retention: keeps newest 30 backups
# Usage: powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 [-BackupRoot "D:\ctms-backups"]

param(
  [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$py = Join-Path $root "app\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  $py = "python"
}
$dbFile = Join-Path $root "app\data\ctms.db"
$uploads = Join-Path $root "app\uploads"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ($BackupRoot) {
  $out = $BackupRoot
} else {
  $out = Join-Path $root "app\backups"
}
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host "[backup] db=$dbFile uploads=$uploads -> $out"

# 1) SQLite online backup (only when default SQLite file exists)
if (Test-Path $dbFile) {
  $dst = Join-Path $out "ctms_$stamp.db"
  $code = "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close(); print('db ok')"
  & $py -c $code $dbFile $dst
  if ($LASTEXITCODE -ne 0) {
    throw "DB backup failed"
  }
  Write-Host "  [ok] $dst"
} else {
  Write-Host "  [skip] no sqlite file (CTMS_DB_URL points elsewhere -> use DB-native backup, see docs/08)"
}

# 2) attachments zip
if (Test-Path $uploads) {
  $zip = Join-Path $out "uploads_$stamp.zip"
  Compress-Archive -Path (Join-Path $uploads "*") -DestinationPath $zip -Force
  Write-Host "  [ok] $zip"
} else {
  Write-Host "  [skip] no uploads dir"
}

# 3) retention: keep newest 30
$days = 30
$cutoff = (Get-Date).AddDays(-$days)
Get-ChildItem -Path $out -File | Where-Object {
  ($_.Extension -eq ".db" -or $_.Extension -eq ".zip") -and $_.LastWriteTime -lt $cutoff
} | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "[backup] done. retention=$days days"
