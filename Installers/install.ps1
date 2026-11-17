# Voktora — installation Windows en UNE commande (PowerShell). NON TESTÉ sous Windows.
#   irm https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/install.ps1 | iex
# Télécharge le .msi de la dernière release, VÉRIFIE son empreinte SHA-256 (SHA256SUMS de la release), puis l'installe.
# Variable : $env:VOKTORA_VERSION = '1.1.6' (défaut : dernière release).
$ErrorActionPreference = 'Stop'
$repo = 'yo-le-zz/Voktora'
$ver = $env:VOKTORA_VERSION
if ($ver) { $ver = $ver.TrimStart('v'); $tag = "v$ver" }
else { $tag = (Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest").tag_name; $ver = $tag.TrimStart('v') }
if ($ver -notmatch '^[0-9A-Za-z.~+-]+$') { throw "version invalide : $ver" }
$asset = "Voktora_${ver}_x64.msi"
$base = "https://github.com/$repo/releases/download/$tag"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("voktora-install-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  Write-Host "Voktora : téléchargement de $asset…"
  Invoke-WebRequest "$base/$asset" -OutFile (Join-Path $tmp $asset)
  Invoke-WebRequest "$base/SHA256SUMS" -OutFile (Join-Path $tmp 'SHA256SUMS')
  $want = (Get-Content (Join-Path $tmp 'SHA256SUMS') | Where-Object { $_ -match ([regex]::Escape($asset) + '$') } | Select-Object -First 1)
  if (-not $want) { throw "aucune empreinte pour $asset dans SHA256SUMS" }
  $want = ($want -split '\s+')[0].ToLower()
  $got = (Get-FileHash (Join-Path $tmp $asset) -Algorithm SHA256).Hash.ToLower()
  if ($want -ne $got) { throw "EMPREINTE INCORRECTE (attendu $want, obtenu $got) : fichier refusé" }
  Write-Host 'Voktora : empreinte SHA-256 vérifiée. Installation (une fenêtre d''autorisation Windows peut s''ouvrir)…'
  Start-Process msiexec.exe -ArgumentList '/i', "`"$(Join-Path $tmp $asset)`"", '/passive' -Wait
  Write-Host 'Voktora : installé (menu Démarrer).'
} finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
