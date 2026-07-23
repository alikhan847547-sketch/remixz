# Sube a los repositorios RemixZ (principal + mirrors)
# Uso:
#   $env:GITHUB_TOKEN = "ghp_tu_token"
#   powershell -ExecutionPolicy Bypass -File .\push_to_github.ps1
#
# Destinos:
#   1) alikhan847547-sketch/remixz   (principal)
#   2) SMPROJECT115/newrepo          (secundario / updates)
#   3) SMPROJECT115/remixz           (mirror legacy)

$ErrorActionPreference = "Stop"
$git = "C:\Program Files\Git\cmd\git.exe"
$pub = "H:\_Desktop\BPM RENAME\remixz_publish"
Set-Location $pub
$token = $env:GITHUB_TOKEN
if (-not $token) { $token = $env:GH_TOKEN }
if (-not $token) {
  Write-Host "Falta GITHUB_TOKEN (PAT con permiso repo en las cuentas)."
  Write-Host '  $env:GITHUB_TOKEN = "ghp_..."'
  exit 1
}

# commit pendientes si hay
& $git add -A
$st = & $git status --porcelain
if ($st) {
  & $git commit -m "chore: sync mirrors (newrepo + remixz)"
}

$remotes = @(
  "https://$token@github.com/alikhan847547-sketch/remixz.git",
  "https://$token@github.com/SMPROJECT115/newrepo.git",
  "https://$token@github.com/SMPROJECT115/remixz.git"
)
$i = 0
foreach ($url in $remotes) {
  $i++
  $name = "origin$i"
  # URL sin token solo para logs
  $safe = ($url -replace '://[^@]+@', '://***@')
  & $git remote remove $name 2>$null
  & $git remote add $name $url
  Write-Host "Pushing -> $safe"
  & $git push -u $name main --force
  if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: fallo push a $safe (token sin acceso a esa cuenta?)"
  } else {
    Write-Host "OK: $safe"
  }
}
Write-Host "Listo. Repos mirror mantenidos (remixz + newrepo)."
