# Installation locale de BM318d (sans installateur tiers).
# Copie l'application, crée un raccourci de démarrage et un désinstalleur.
param(
  [string]$TargetDir = "$env:LOCALAPPDATA\BM318d",
  [switch]$NoShortcuts
)

$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

$fichiers = @('MissionControl.py','mc_agent.py','mc_plan.py','mc_sandbox.py','mc_sandbox_wsl.py','mc_sandbox_linux.py','mc_security.py','mc_connectors.py','mc_credentials.py','mc_documents.py','BM318d-WebServer.py',
              'BM318d-Railway.html','mission.js','mission.css','connectors.js','security-ui.js','workspace.js','workspace.css','installer\version.json',
              'BM318d-Controleur.pyw','BM318d-Stop.py','LANCER-BM318d-RAILWAY.cmd','requirements-v22.txt',
              'README.md','MISSION-CONTROL-LISEZMOI.txt','docs\DELIVERY-V25-HOTFIX.md','docs\SECURITY-STATUS.md')
$copies = 0
foreach ($nom in $fichiers) {
  $chemin = Join-Path $source $nom
  if (Test-Path $chemin) {
    $destination = Join-Path $TargetDir $nom
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item $chemin $destination -Force
    $copies++
  }
}

# La base et les sauvegardes ne sont copiées que si elles n'existent pas déjà.
foreach ($dossier in @('backups')) {
  $cible = Join-Path $TargetDir $dossier
  if (-not (Test-Path $cible)) { New-Item -ItemType Directory -Path $cible | Out-Null }
}
$base = Join-Path $source 'bm318d.sqlite3'
if ((Test-Path $base) -and -not (Test-Path (Join-Path $TargetDir 'bm318d.sqlite3'))) {
  Copy-Item $base (Join-Path $TargetDir 'bm318d.sqlite3') -Force
}

$lanceur = @"
@echo off
cd /d "%~dp0"
start "" pythonw "%~dp0BM318d-Controleur.pyw"
"@
Set-Content -Path (Join-Path $TargetDir 'LANCER-BM318d.cmd') -Value $lanceur -Encoding ASCII

$arret = @"
@echo off
cd /d "%~dp0"
python "%~dp0BM318d-Stop.py"
"@
Set-Content -Path (Join-Path $TargetDir 'ARRETER-BM318d.cmd') -Value $arret -Encoding ASCII

if (-not $NoShortcuts) {
  $shell = New-Object -ComObject WScript.Shell
  $bureau = [Environment]::GetFolderPath('Desktop')
  $raccourci = $shell.CreateShortcut((Join-Path $bureau 'BM318d.lnk'))
  $raccourci.TargetPath = Join-Path $TargetDir 'LANCER-BM318d.cmd'
  $raccourci.WorkingDirectory = $TargetDir
  $raccourci.Description = 'BM318d Control Center'
  $raccourci.Save()
}

$desinstaller = @"
`$dossier = "$TargetDir"
`$raccourci = Join-Path ([Environment]::GetFolderPath('Desktop')) 'BM318d.lnk'
if (Test-Path `$raccourci) { Remove-Item `$raccourci -Force }
Write-Host 'Les donnees restent dans' `$dossier 'si vous ne le supprimez pas.'
"@
Set-Content -Path (Join-Path $TargetDir 'desinstaller.ps1') -Value $desinstaller -Encoding UTF8

Write-Host "BM318d installe dans $TargetDir ($copies fichiers)."
Write-Host "Lancement : $(Join-Path $TargetDir 'LANCER-BM318d.cmd')"
