; ============================================================
;  Pulsemail — Outreach Suite
;  Script Inno Setup para generar instalador profesional
; ============================================================
;  Genera:  installer_output\PulsemailSetup_v{Version}.exe
;
;  Características:
;    - Detecta versión previa instalada y ofrece "Actualizar"
;    - Recomienda backup antes de actualizar
;    - Crea acceso directo en escritorio + menú inicio
;    - Aparece en "Agregar/quitar programas" con logo y nombre
;    - Desinstalador NO borra los datos del usuario por defecto
;      (config.json, contactos.csv, historial, etc.)
; ============================================================

#define MyAppName       "Pulsemail"
#define MyAppFullName   "Pulsemail — Outreach Suite"
#define MyAppPublisher  "Pulsemail"
; La versión se lee del archivo VERSION en la raíz del proyecto.
; Fuente única de verdad: bumpear con `python bump_version.py patch`
; y todos los artefactos (build_installer.bat, este .iss, CHANGELOG)
; quedan sincronizados.
#define MyAppVersion    Trim(FileRead(FileOpen("..\VERSION")))
#define MyAppExeName    "Pulsemail.exe"
#define MyAppURL        "https://pulsemail.app"

[Setup]
; AppId fijo (NO cambiar entre versiones — así Inno detecta updates)
AppId={{B7E89C4D-3F2A-4B1E-9C5D-8A3F6E2D1B7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppFullName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppFullName}
VersionInfoProductName={#MyAppName}

; Carpeta destino: %LOCALAPPDATA%\Pulsemail (no requiere admin para instalar
; ni para escribir datos. Es lo que hacen Slack, Discord, Notion, etc.)
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output
OutputDir=..\installer_output
OutputBaseFilename=PulsemailSetup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\logo-app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppFullName}

; Idioma del wizard
ShowLanguageDialog=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "Crear acceso directo en el &escritorio"; \
    GroupDescription: "Accesos directos:"; \
    Flags: checkedonce
Name: "quicklaunchicon"; \
    Description: "Crear acceso directo en la &barra de tareas"; \
    GroupDescription: "Accesos directos:"; \
    Flags: unchecked

[Files]
; Bundle generado por flet pack (todo lo que está en dist\Pulsemail va al instalador)
Source: "..\dist\{#MyAppName}\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; \
    Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Iniciar {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Sólo borra archivos de la carpeta de instalación. Los datos del usuario
; (config.json, contactos.csv, historial, etc.) quedan intactos al
; desinstalar. Si el usuario los reinstala más tarde, retoma donde estaba.
; Si querés desinstalación "completa" pidiéndole al usuario, ver [Code].
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\python*.dll"
Type: files; Name: "{app}\base_library.zip"

[Code]
// ============================================================
//  Detección de versión previa + diálogo de actualización
// ============================================================

const
  UninstallRegKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B7E89C4D-3F2A-4B1E-9C5D-8A3F6E2D1B7C}_is1';

function GetInstalledVersion(): String;
var
  InstalledVer: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, UninstallRegKey, 'DisplayVersion', InstalledVer) then
    Result := InstalledVer
  else if RegQueryStringValue(HKLM, UninstallRegKey, 'DisplayVersion', InstalledVer) then
    Result := InstalledVer;
end;

function InitializeSetup(): Boolean;
var
  PrevVersion: String;
  Respuesta: Integer;
begin
  Result := True;
  PrevVersion := GetInstalledVersion();

  if PrevVersion <> '' then
  begin
    if PrevVersion = '{#MyAppVersion}' then
    begin
      Respuesta := MsgBox(
        'Pulsemail v' + PrevVersion + ' ya está instalado en esta computadora.' + #13#10 + #13#10 +
        '¿Querés reinstalarlo?' + #13#10 + #13#10 +
        'Tus datos (configuración, contactos, historial de campañas, ' +
        'rechazados, respuestas y firma) se mantienen intactos.',
        mbConfirmation, MB_YESNO);
      if Respuesta = IDNO then
        Result := False;
    end
    else
    begin
      Respuesta := MsgBox(
        'Detectamos una instalación previa de Pulsemail (v' + PrevVersion + ').' + #13#10 +
        'Esta versión: v{#MyAppVersion}.' + #13#10 + #13#10 +
        '¿Querés ACTUALIZAR a la nueva versión?' + #13#10 + #13#10 +
        '──────────────────────────────────────────────' + #13#10 +
        'IMPORTANTE: Antes de actualizar te recomendamos hacer un BACKUP ' +
        'de tu configuración. Para hacerlo:' + #13#10 + #13#10 +
        '   1. Abrí Pulsemail (versión actual)' + #13#10 +
        '   2. Andá a Configuración → Datos' + #13#10 +
        '   3. Apretá "Exportar configuración completa"' + #13#10 +
        '   4. Guardá el ZIP en un lugar seguro' + #13#10 + #13#10 +
        'La actualización NO borra tus datos, pero el backup es la ' +
        'práctica recomendada por si algo falla.' + #13#10 +
        '──────────────────────────────────────────────' + #13#10 + #13#10 +
        '¿Continuar con la actualización?',
        mbConfirmation, MB_YESNOCANCEL);

      if (Respuesta = IDNO) or (Respuesta = IDCANCEL) then
        Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Sólo mostramos mensaje de bienvenida en instalación nueva
    if GetInstalledVersion() = '' then
    begin
      // primera vez (este check ya se ejecutó después de instalar, así que
      // siempre va a haber versión — lo dejamos sin mensaje para no spamear)
    end;
  end;
end;

// ============================================================
//  Desinstalador: preguntar si borrar también los datos
// ============================================================

function InitializeUninstall(): Boolean;
var
  Respuesta: Integer;
begin
  Result := True;
  Respuesta := MsgBox(
    '¿Querés desinstalar Pulsemail?' + #13#10 + #13#10 +
    'Tus datos (configuración, contactos, historial, etc.) ' +
    'NO se van a borrar — quedan en la carpeta de instalación ' +
    'por si reinstalás más tarde.' + #13#10 + #13#10 +
    'Si querés borrar TODO incluyendo tus datos, exportá ' +
    'primero un backup desde Configuración → Datos.',
    mbConfirmation, MB_YESNO);

  if Respuesta = IDNO then
    Result := False;
end;
