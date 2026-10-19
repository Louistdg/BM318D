# Mise a jour controlee de DIOPTRE : copie les fichiers d'une version preparee,
# apres avoir sauvegarde l'installation actuelle. Aucune mise a jour automatique.
param(
  [Parameter(Mandatory=$true)][string]$Source,
  [Parameter(Mandatory=$true)][string]$TargetDir
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Source)) { throw "Source introuvable : $Source" }
if (-not (Test-Path $TargetDir)) { throw "Installation introuvable : $TargetDir" }

$horodatage = Get-Date -Format 'yyyyMMdd-HHmmss'
$sauvegarde = Join-Path $TargetDir "backups\pre-maj-$horodatage"
New-Item -ItemType Directory -Force -Path $sauvegarde | Out-Null

$fichiers = @('MissionControl.py','mc_agent.py','mc_plan.py','mc_sandbox.py','mc_sandbox_wsl.py','mc_sandbox_linux.py','mc_security.py','mc_connectors.py','mc_credentials.py','DIOPTRE-WebServer.py',
              'DIOPTRE.html','mission.js','mission.css','connectors.js','security-ui.js','requirements-v22.txt','V2.2-IMPLEMENTATION.md','V2.3-SECURITE.md',
              'DIOPTRE-Controleur.pyw','DIOPTRE-Stop.py','DIOPTRE-Fenetre.pyw')
$copies = 0
foreach ($nom in $fichiers) {
  $cheminSource = Join-Path $Source $nom
  if (Test-Path $cheminSource) {
    $cible = Join-Path $TargetDir $nom
    if (Test-Path $cible) { Copy-Item $cible (Join-Path $sauvegarde $nom) -Force }
    Copy-Item $cheminSource $cible -Force
    $copies++
  }
}
$manifeste = Join-Path $Source 'version.json'
if (Test-Path $manifeste) { Copy-Item $manifeste (Join-Path $TargetDir 'version.json') -Force }

Write-Host "Mise a jour : $copies fichiers copies. Sauvegarde : $sauvegarde"
