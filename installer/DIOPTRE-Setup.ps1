# Installation locale de DIOPTRE (sans installateur tiers).
# Copie l'application, crée un raccourci de démarrage et un désinstalleur.
param(
  [string]$TargetDir = "$env:LOCALAPPDATA\DIOPTRE",
  [switch]$NoShortcuts
)

$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

$fichiers = @('MissionControl.py','mc_agent.py','mc_plan.py','mc_sandbox.py','mc_sandbox_wsl.py','mc_sandbox_linux.py','mc_security.py','mc_connectors.py','mc_credentials.py','mc_documents.py','mc_actions.py','mc_backups.py','mc_jobs.py','mc_legacy.py','mc_missions.py','mc_routes.py','DIOPTRE.html','mission.js','mission.css','connectors.js','security-ui.js','workspace.js','workspace.css','installer\version.json',
              'DIOPTRE-Controleur.pyw','DIOPTRE-Stop.py','LANCER-DIOPTRE-RAILWAY.cmd','requirements-v22.txt',
              'README.md','DIOPTRE-LISEZMOI.txt','docs\DELIVERY-V25-HOTFIX.md','docs\SECURITY-STATUS.md','mc_demo.py')
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
$base = Join-Path $source 'dioptre.sqlite3'
if ((Test-Path $base) -and -not (Test-Path (Join-Path $TargetDir 'dioptre.sqlite3'))) {
  Copy-Item $base (Join-Path $TargetDir 'dioptre.sqlite3') -Force
}

$lanceur = @"
@echo off
cd /d "%~dp0"
start "" pythonw "%~dp0DIOPTRE-Controleur.pyw"
"@

$demo = @"
@echo off
cd /d "%~dp0"
echo Creation d'une demonstration complete (projet, agents, mission, job approuve, revue, note)...
python "%~dp0mc_demo.py"
echo.
pause
"@
Set-Content -Path (Join-Path $TargetDir 'LANCER-DIOPTRE-DEMO.cmd') -Value $demo -Encoding ASCII

Set-Content -Path (Join-Path $TargetDir 'LANCER-DIOPTRE.cmd') -Value $lanceur -Encoding ASCII

$arret = @"
@echo off
cd /d "%~dp0"
python "%~dp0DIOPTRE-Stop.py"
"@
Set-Content -Path (Join-Path $TargetDir 'ARRETER-DIOPTRE.cmd') -Value $arret -Encoding ASCII

if (-not $NoShortcuts) {
  $shell = New-Object -ComObject WScript.Shell
  $bureau = [Environment]::GetFolderPath('Desktop')
  $raccourci = $shell.CreateShortcut((Join-Path $bureau 'DIOPTRE.lnk'))
  $raccourci.TargetPath = Join-Path $TargetDir 'LANCER-DIOPTRE.cmd'
  $raccourci.WorkingDirectory = $TargetDir
  $raccourci.Description = 'DIOPTRE Control Center'
  $raccourci.Save()
}

$desinstaller = @"
`$dossier = "$TargetDir"
`$raccourci = Join-Path ([Environment]::GetFolderPath('Desktop')) 'DIOPTRE.lnk'
if (Test-Path `$raccourci) { Remove-Item `$raccourci -Force }
Write-Host 'Les donnees restent dans' `$dossier 'si vous ne le supprimez pas.'
"@
Set-Content -Path (Join-Path $TargetDir 'desinstaller.ps1') -Value $desinstaller -Encoding UTF8

Write-Host "DIOPTRE installe dans $TargetDir ($copies fichiers)."
Write-Host "Lancement : $(Join-Path $TargetDir 'LANCER-DIOPTRE.cmd')"
