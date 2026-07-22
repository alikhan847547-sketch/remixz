# Sube a AMBOS repositorios RemixZ
# Uso:
#   $env:GITHUB_TOKEN = "ghp_tu_token"
#   powershell -ExecutionPolicy Bypass -File .\push_to_github.ps1

$ErrorActionPreference = "Stop"
$git = "C:\Program Files\Git\cmd\git.exe"
$pub = "H:\_Desktop\BPM RENAME\remixz_publish"
Set-Location $pub
$token = $env:GITHUB_TOKEN
if (-not $token) { $token = $env:GH_TOKEN }
if (-not $token) {
  Write-Host "Falta GITHUB_TOKEN (PAT con permiso repo en ambas cuentas o en org)."
  Write-Host '  $env:GITHUB_TOKEN = "ghp_..."'
  exit 1
}

# commit pendientes si hay
& $git add -A
$st = & $git status --porcelain
if ($st) {
  & $git commit -m "v3.1.6: dual-repo updates + ClubRemix proximamente"
}

$remotes = @(
  "https://$token@github.com/alikhan847547-sketch/remixz.git",
  "https://$token@github.com/SMPROJECT115/remixz.git"
)
$i = 0
foreach ($url in $remotes) {
  $i++
  $name = "origin$i"
  & $git remote remove $name 2>$null
  & $git remote add $name $url
  Write-Host "Pushing -> $url"
  & $git push -u $name main --force
  if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: fallo push a $url (token sin acceso a esa cuenta?)"
  } else {
    Write-Host "OK: $url"
  }
}
Write-Host "Listo. Repos mirror mantenidos."
