# Voktora — mode LIVE (Windows, PowerShell) : essayer Voktora sans rien installer. NON TESTÉ sous Windows.
#   irm https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/live/install-live.ps1 | iex
# Tout vit dans %TEMP%\voktora-live-XXXXXXXX et est supprimé à la fermeture.
$ErrorActionPreference = 'Stop'
$repo = 'yo-le-zz/Voktora'
$root = [System.IO.Path]::GetTempPath().TrimEnd('\')
Get-ChildItem -Path $root -Directory -Filter 'voktora-live-*' -ErrorAction SilentlyContinue | ForEach-Object {
  if (Test-Path (Join-Path $_.FullName '.voktora-live')) {
    $old = 0; try { $old = [int](Get-Content (Join-Path $_.FullName '.pid')) } catch {}
    if (-not ($old -gt 1 -and (Get-Process -Id $old -ErrorAction SilentlyContinue))) { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
  }
}
$suffix = -join ((48..57) + (97..122) | Get-Random -Count 8 | ForEach-Object { [char]$_ })
$live = Join-Path $root "voktora-live-$suffix"
New-Item -ItemType Directory -Path $live | Out-Null
New-Item -ItemType File -Path (Join-Path $live '.voktora-live') | Out-Null
Set-Content -Path (Join-Path $live '.pid') -Value $PID
try {
  $ref = $env:VOKTORA_LIVE_REF
  if (-not $ref) { try { $ref = (Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest").tag_name } catch { $ref = 'main' } }
  if ($ref -notmatch '^[A-Za-z0-9._/-]+$') { $ref = 'main' }
  $zip = Join-Path $live 'src.zip'
  $url = if ($ref -eq 'main') { "https://github.com/$repo/archive/refs/heads/main.zip" } else { "https://github.com/$repo/archive/refs/tags/$ref.zip" }
  Write-Host "Voktora live : téléchargement ($ref)…"
  try { Invoke-WebRequest $url -OutFile $zip } catch { Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip }
  Expand-Archive $zip -DestinationPath (Join-Path $live 'src')
  $app = (Get-ChildItem (Join-Path $live 'src') -Directory | Select-Object -First 1).FullName
  $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
  if (-not $uv) {
    Write-Host 'Voktora live : installation temporaire de uv…'
    $env:UV_UNMANAGED_INSTALL = Join-Path $live 'uv'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $uv = Join-Path $live 'uv\uv.exe'
  }
  $env:UV_CACHE_DIR = Join-Path $live 'cache\uv'; $env:UV_PYTHON_INSTALL_DIR = Join-Path $live 'python'
  & $uv venv --quiet --python 3.13 (Join-Path $live 'venv')
  & $uv pip install --quiet --python (Join-Path $live 'venv\Scripts\python.exe') 'pyside6>=6.5' 'cryptography>=42.0'
  $env:VOKTORA_LIVE_DIR = $live; $env:VOKTORA_NO_NATIVE = '1'
  Write-Host 'Voktora live : lancement — tout sera supprimé à la fermeture.'
  & (Join-Path $live 'venv\Scripts\python.exe') (Join-Path $app 'voktora\main.py') --live
} finally {
  if ($env:VOKTORA_LIVE_KEEP -ne '1') { Remove-Item -Recurse -Force $live -ErrorAction SilentlyContinue; Write-Host 'Voktora live : tout a été supprimé.' }
}
