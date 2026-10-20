; Installateur Windows de TREDIO â€” genere avec Inno Setup 6.
; Installation par utilisateur, sans droits administrateur.

#ifndef PayloadDir
#define PayloadDir "payload"
#endif
#ifndef IconPath
#define IconPath "dioptre.ico"
#endif
#define AppName "TREDIO"
#define AppVersion "2.8.4"
#define AppPublisher "TREDIO"
#define AppExe "LANCER-TREDIO.cmd"

[Setup]
#ifdef TestBuild
AppId=TREDIO-Installer-Isolated-Test
Uninstallable=no
CreateUninstallRegKey=no
#else
AppId={{7E3C1A52-9B4D-4C2E-9F1A-2D5B6C7E8F90}
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\DIOPTRE
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=build
OutputBaseFilename=TREDIO-Setup-{#AppVersion}-r2
SetupIconFile={#IconPath}
UninstallDisplayIcon={app}\dioptre.ico
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Creer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#IconPath}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
#ifndef TestBuild
Name: "{group}\TREDIO"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\dioptre.ico"
Name: "{group}\Desinstaller TREDIO"; Filename: "{uninstallexe}"
Name: "{autodesktop}\TREDIO"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\dioptre.ico"; Tasks: bureau

#endif

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer TREDIO maintenant"; Flags: postinstall nowait skipifsilent shellexec

[Code]
function PythonCompatible(const Exe: String): Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(Exe,
    '-I -c "import sys,sqlite3; sys.exit(0 if sys.version_info[:2] == (3,14) else 1)"',
    ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
end;

function InitializeSetup(): Boolean;
begin
  Result := PythonCompatible('python.exe');
  if Result then Result := PythonCompatible('pythonw.exe');
  if not Result then
  begin
    Log('TREDIO: Python 3.14 avec sqlite3 et pythonw requis. Installation annulee.');
    if not WizardSilent then
      MsgBox('Python 3.14 est requis avant TREDIO.' + #13#10 +
        'Installez-le depuis https://www.python.org/downloads/windows/ en cochant Add python.exe to PATH.' + #13#10 +
        'Fermez puis relancez cet installateur. Aucun fichier TREDIO n''a ete installe.',
        mbError, MB_OK);
  end;
end;
