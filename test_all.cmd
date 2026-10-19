@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Lanceur des verifications documentees dans DELIVERY-V2.5.1.md.
rem Executer depuis n'importe quel repertoire sous Windows.
rem Arrete la campagne au premier echec ; ne modifie pas la base de production.

cd /d "%~dp0"
if errorlevel 1 (
    echo ERREUR : impossible d'ouvrir la racine du projet.
    exit /b 2
)

echo === BM318D - Verification complete V2.5.1 ===

set "ETAPE=01/12 - Compilation Python"
echo.
echo [%ETAPE%]
python -m compileall -q .
if errorlevel 1 goto :echec

set "ETAPE=02/12 - Controle des espaces Git"
echo.
echo [%ETAPE%]
git diff --check
if errorlevel 1 goto :echec

set "ETAPE=03/12 - Fichiers importes et sauvegardes"
echo.
echo [%ETAPE%]
python -m unittest -q test_documents
if errorlevel 1 goto :echec

set "ETAPE=04/12 - Application"
echo.
echo [%ETAPE%]
python test_app.py
if errorlevel 1 goto :echec

set "ETAPE=05/12 - HTTP et prompts"
echo.
echo [%ETAPE%]
python test_http.py
if errorlevel 1 goto :echec

set "ETAPE=06/12 - Jobs"
echo.
echo [%ETAPE%]
python test_jobs.py
if errorlevel 1 goto :echec

set "ETAPE=07/12 - Revues et preuves"
echo.
echo [%ETAPE%]
python test_review.py
if errorlevel 1 goto :echec

set "ETAPE=08/12 - Installation propre"
echo.
echo [%ETAPE%]
python test_clean_install.py
if errorlevel 1 goto :echec

set "ETAPE=09/12 - Securite"
echo.
echo [%ETAPE%]
python test_securite.py
if errorlevel 1 goto :echec

set "ETAPE=10/12 - Contrat UI"
echo.
echo [%ETAPE%]
node test_interface_contrat.mjs
if errorlevel 1 goto :echec

set "ETAPE=11/12 - Chat UI"
echo.
echo [%ETAPE%]
node test_chat_ui.mjs
if errorlevel 1 goto :echec

set "ETAPE=12/12 - Interface Chrome"
echo.
echo [%ETAPE%]
node test_ui.mjs
if errorlevel 1 goto :echec

echo.
echo === SUCCES : toutes les verifications sont passees ===
exit /b 0

:echec
set "CODE_RETOUR=%errorlevel%"
echo.
echo === ECHEC : %ETAPE% - code %CODE_RETOUR% ===
exit /b %CODE_RETOUR%
