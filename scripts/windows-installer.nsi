; The PDF Remediator setup program: a standard NSIS installer, built by package-windows.py with the same NSIS (3.x, Modern UI 2)
; that Tauri uses for the other OpenStage-family apps, so it has the same pages and works the same way:
; Welcome, Licence, Choose Install Location, Installing, Finish (Run PDF Remediator, Create desktop shortcut).
; It installs for the current Windows account only (no administrator rights), lists itself in Settings > Apps with an uninstaller,
; and keeps the person's saved reviews (the output folder) when it updates or uninstalls, unless they tick the box to delete them.
; The page order, the uninstall check box and the command-line switches (/S, /D=, /NS) follow Tauri's NSIS template
; (https://github.com/tauri-apps/tauri, MIT or Apache-2.0); the script itself is written for this program.
;
; package-windows.py puts these defines in front of this file (installer-bound.nsi):
;   PRODUCTNAME, VERSION, VERSIONWITHBUILD, PUBLISHER, COPYRIGHT, HOMEPAGE, PAYLOAD (folder), LICENSEFILE, ICONFILE, OUTFILE, MINVC
;   and, when signing, UNINSTALLERSIGNCOMMAND.

Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2
SetCompressor /SOLID lzma
RequestExecutionLevel user

!include MUI2.nsh
!include nsDialogs.nsh
!include WinMessages.nsh
!include FileFunc.nsh
!include LogicLib.nsh
!include WordFunc.nsh
!include x64.nsh
!include "Win\COM.nsh"

!define MAINBINARY "PDF Remediator.exe"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define PRODUCTKEY "Software\${PRODUCTNAME}"
!define VCPAGE "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist"

Name "${PRODUCTNAME}"
BrandingText "${COPYRIGHT}"
OutFile "${OUTFILE}"
; The last part of this folder is added to whatever folder is picked with Browse, as in the other suite installers.
InstallDir "$LOCALAPPDATA\${PRODUCTNAME}"
InstallDirRegKey HKCU "${PRODUCTKEY}" ""

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

!ifdef UNINSTALLERSIGNCOMMAND
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

Var NoShortcutMode
Var DeleteDataCheckbox
Var DeleteDataState

!define MUI_ICON "${ICONFILE}"
!define MUI_UNICON "${ICONFILE}"

; 1. Welcome
!insertmacro MUI_PAGE_WELCOME
; 2. Licence
!insertmacro MUI_PAGE_LICENSE "${LICENSEFILE}"
; 3. Choose Install Location
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE CheckInstallFolder
!insertmacro MUI_PAGE_DIRECTORY
; 4. Installing
!insertmacro MUI_PAGE_INSTFILES
; 5. Finish. The details stay on screen until Next, as in the other suite installers.
!define MUI_FINISHPAGE_NOAUTOCLOSE
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Create desktop shortcut"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION CreateDesktopShortcut
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunProgram
!insertmacro MUI_PAGE_FINISH

; Uninstaller: confirm (with a check box for the saved reviews), then uninstalling.
!define MUI_PAGE_CUSTOMFUNCTION_SHOW un.ConfirmShow
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE un.ConfirmLeave
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; Sets $0 to 1 when one of the program's own files is in use, which means PDF Remediator (or its local service) is still open.
; A running program cannot be opened for writing; nothing is written to it.
!macro TRY_OPEN path
  ${If} $0 = 0
  ${AndIf} ${FileExists} "${path}"
    ClearErrors
    FileOpen $9 "${path}" a
    ${If} ${Errors}
      StrCpy $0 1
    ${Else}
      FileClose $9
    ${EndIf}
  ${EndIf}
!macroend

!macro WAIT_UNTIL_CLOSED
  ${Do}
    StrCpy $0 0
    !insertmacro TRY_OPEN "$INSTDIR\${MAINBINARY}"
    !insertmacro TRY_OPEN "$INSTDIR\runtime\python\python.exe"
    !insertmacro TRY_OPEN "$INSTDIR\runtime\ocr\python.exe"
    !insertmacro TRY_OPEN "$INSTDIR\runtime\java\bin\java.exe"
    !insertmacro TRY_OPEN "$INSTDIR\runtime\tesseract\tesseract.exe"
    ${If} $0 = 0
      ${Break}
    ${EndIf}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "${PRODUCTNAME} is open. Close its window, wait a moment, then click Retry." /SD IDCANCEL IDRETRY +2
    Abort "${PRODUCTNAME} is open. Close it, then try again."
  ${Loop}
!macroend

; Sets $R8 to 1 when $INSTDIR holds an installed copy of this program: the program, its installation marker and its manifest are
; there, and the manifest names the program. Copies made by the first two versions of this installer have no product line in their
; manifest; their schema line, which only this program's packages use, names them instead. Only such a folder is updated or uninstalled.
!macro IS_OUR_INSTALLATION
  StrCpy $R8 0
  ${If} ${FileExists} "$INSTDIR\package-manifest.json"
  ${AndIf} ${FileExists} "$INSTDIR\${MAINBINARY}"
  ${AndIf} ${FileExists} "$INSTDIR\.installation-complete.json"
    ClearErrors
    FileOpen $R7 "$INSTDIR\package-manifest.json" r
    ${IfNot} ${Errors}
      ${Do}
        ClearErrors
        FileRead $R7 $R6
        ${If} ${Errors}
          ${Break}
        ${EndIf}
        ${If} $R6 == '  "product": "${PRODUCTNAME}",$\n'
        ${OrIf} $R6 == '  "product": "${PRODUCTNAME}",$\r$\n'
        ${OrIf} $R6 == '  "schema": "windows-internal-package-1",$\n'
        ${OrIf} $R6 == '  "schema": "windows-internal-package-1",$\r$\n'
          StrCpy $R8 1
          ${Break}
        ${EndIf}
      ${Loop}
      FileClose $R7
    ${EndIf}
  ${EndIf}
!macroend
Function IsOurInstallation
  !insertmacro IS_OUR_INSTALLATION
FunctionEnd
Function un.IsOurInstallation
  !insertmacro IS_OUR_INSTALLATION
FunctionEnd

; Removes an installed copy's program files: the ones its own manifest lists ("files"), one by one, then each folder above them that
; that leaves empty, with the cache the program's Python writes beside its .py files (__pycache__). Every version's manifest lists
; exactly what that version installed, so an update removes the older version's files and an uninstall this version's, and nothing
; else: a file the person put in one of those folders stays, and so does a same-named folder that was never the program's. A listed
; name with a drive, a leading separator or ".." in it is skipped. The output folder (saved reviews) is never listed.
; Only called after IsOurInstallation said yes ($R8 = 1). Uses $R0-$R7 and $6-$9.
!macro REMOVE_PROGRAM
  ${If} $R8 = 1
    ClearErrors
    FileOpen $R7 "$INSTDIR\package-manifest.json" r
    ${IfNot} ${Errors}
      StrCpy $R5 0
      ${Do}
        ClearErrors
        FileRead $R7 $R6
        ${If} ${Errors}
          ${Break}
        ${EndIf}
        ${Do}
          StrCpy $R4 $R6 1 -1
          ${If} $R4 == "$\n"
          ${OrIf} $R4 == "$\r"
            StrCpy $R6 $R6 -1
          ${Else}
            ${Break}
          ${EndIf}
        ${Loop}
        ${If} $R5 = 0
          ${If} $R6 == '  "files": {'
            StrCpy $R5 1
          ${EndIf}
          ${Continue}
        ${EndIf}
        StrCpy $R4 $R6 3
        ${If} $R4 == "  }"
          ${Break}
        ${EndIf}
        ; Each entry is four spaces, "name": "64 hex digits", and a comma unless it is the last one.
        StrLen $R3 $R6
        StrCpy $R4 $R6 1 -1
        ${If} $R4 == ","
          IntOp $R3 $R3 - 1
        ${EndIf}
        IntOp $R3 $R3 - 74
        ${If} $R3 < 1
          ${Continue}
        ${EndIf}
        StrCpy $R4 $R6 5
        IntOp $R2 $R3 + 5
        StrCpy $R1 $R6 4 $R2
        ${If} $R4 != '    "'
        ${OrIf} $R1 != '": "'
          ${Continue}
        ${EndIf}
        StrCpy $R4 $R6 $R3 5
        ; The name with Windows separators, refused if it could reach outside the folder.
        StrCpy $R1 ""
        StrCpy $R0 0
        StrCpy $9 0
        ${Do}
          StrCpy $8 $R4 1 $R0
          ${If} $8 == ""
            ${Break}
          ${EndIf}
          StrCpy $7 $R4 2 $R0
          ${If} $8 == ":"
          ${OrIf} $8 == "\"
          ${OrIf} $7 == ".."
            StrCpy $9 1
          ${EndIf}
          ${If} $8 == "/"
            StrCpy $8 "\"
          ${EndIf}
          StrCpy $R1 "$R1$8"
          IntOp $R0 $R0 + 1
        ${Loop}
        StrCpy $8 $R1 1
        ${If} $8 == "\"
          StrCpy $9 1
        ${EndIf}
        ${If} $9 = 0
          Delete "$INSTDIR\$R1"
          StrCpy $6 0
          StrCpy $8 $R1 3 -3
          ${If} $8 == ".py"
            StrCpy $6 1
          ${EndIf}
          ; Each folder above the file, if that leaves it empty.
          ${Do}
            StrLen $R0 $R1
            ${Do}
              IntOp $R0 $R0 - 1
              ${If} $R0 < 0
                ${Break}
              ${EndIf}
              StrCpy $8 $R1 1 $R0
              ${If} $8 == "\"
                ${Break}
              ${EndIf}
            ${Loop}
            ${If} $R0 < 1
              ${If} $6 = 1
                RMDir /r "$INSTDIR\__pycache__"
              ${EndIf}
              ${Break}
            ${EndIf}
            StrCpy $R1 $R1 $R0
            ${If} $6 = 1
              RMDir /r "$INSTDIR\$R1\__pycache__"
              StrCpy $6 0
            ${EndIf}
            RMDir "$INSTDIR\$R1"
          ${Loop}
        ${EndIf}
      ${Loop}
      FileClose $R7
    ${EndIf}
    Delete "$INSTDIR\package-manifest.json"
    Delete "$INSTDIR\.installation-complete.json"
  ${EndIf}
!macroend

; The chosen folder must be new, empty, or an installed copy of this program (which is then updated, keeping its saved reviews).
; Sets $R9 to "" when it can be used, otherwise to the message that says why not.
Function ValidateInstallFolder
  StrCpy $R9 ""
  StrLen $0 $INSTDIR
  ${If} $0 > 100
    StrCpy $R9 "Choose a shorter folder (at most 100 characters). Some of the program's files have long names."
    Return
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\*.*"
    StrCpy $1 0
    FindFirst $2 $3 "$INSTDIR\*.*"
    ${DoWhile} $3 != ""
      ${If} $3 != "."
      ${AndIf} $3 != ".."
        StrCpy $1 1
        ${Break}
      ${EndIf}
      FindNext $2 $3
    ${Loop}
    FindClose $2
    ${If} $1 = 1
      Call IsOurInstallation
      ${If} $R8 != 1
        StrCpy $R9 "That folder already has other files in it.$\n$\nChoose a new or empty folder, or the folder ${PRODUCTNAME} is already installed in."
      ${EndIf}
    ${EndIf}
  ${EndIf}
FunctionEnd

Function .onInit
  ${GetOptions} $CMDLINE "/NS" $0
  ${IfNot} ${Errors}
    StrCpy $NoShortcutMode 1
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "${PRODUCTNAME} needs 64-bit Windows 10 or 11." /SD IDOK
    Abort
  ${EndIf}
  ; A silent setup (/S /D=folder) never shows the folder page, so the same check runs here; setup ends with exit code 2 if it fails.
  ${If} ${Silent}
    Call ValidateInstallFolder
    ${If} $R9 != ""
      SetErrorLevel 2
      Quit
    ${EndIf}
  ${EndIf}
FunctionEnd

Function CheckInstallFolder
  Call ValidateInstallFolder
  ${If} $R9 != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

; CheckVcRuntime: is Microsoft's Visual C++ runtime there and new enough?
!include "windows-vc-runtime.nsh"

Section Install
  SetOutPath "$INSTDIR"
  !insertmacro WAIT_UNTIL_CLOSED

  Call CheckVcRuntime
  ${If} $R9 != ""
    DetailPrint "Microsoft's Visual C++ Redistributable (x64) is needed: $R9"
    MessageBox MB_YESNO|MB_ICONINFORMATION "${PRODUCTNAME} needs Microsoft's free $\"Visual C++ Redistributable$\" (x64, version ${MINVC} or newer), and this computer doesn't have it yet.$\n$\n$R9$\n$\nSetup will finish installing ${PRODUCTNAME}. Install the Redistributable from Microsoft before you open it.$\n$\nOpen Microsoft's page now?" /SD IDNO IDNO +2
    ExecShell "open" "${VCPAGE}"
  ${EndIf}

  ; Updating a copy that is already here: its old program files go first, the ones its own manifest lists, so nothing of the old
  ; version is left mixed in. Saved reviews (the output folder) stay.
  Call IsOurInstallation
  ${If} $R8 = 1
    DetailPrint "Removing the previous version's program files. Saved reviews stay."
    !insertmacro REMOVE_PROGRAM
  ${EndIf}

  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}\*"

  ; The program opens only a complete installation: this marker is written last, after every file is in place.
  FileOpen $0 "$INSTDIR\.installation-complete.json" w
  FileWrite $0 '{"installer": "nsis", "status": "installed", "version": "${VERSION}"}'
  FileClose $0

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Remembered for the next installation, and the entry in Settings > Apps.
  WriteRegStr HKCU "${PRODUCTKEY}" "" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\${MAINBINARY}$\""
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegStr HKCU "${UNINSTKEY}" "QuietUninstallString" "$\"$INSTDIR\uninstall.exe$\" /S"
  WriteRegStr HKCU "${UNINSTKEY}" "URLInfoAbout" "${HOMEPAGE}"
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ; The size Settings > Apps shows: every file in the folder and its subfolders, in kilobytes.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" "$0"

  ${If} $NoShortcutMode != 1
    SetOutPath "$INSTDIR"
    CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARY}" "" "$INSTDIR\${MAINBINARY}" 0
    ; The finish page offers the desktop shortcut; a silent installation makes it straight away.
    ${If} ${Silent}
      Call CreateDesktopShortcut
    ${EndIf}
  ${EndIf}
SectionEnd

Function CreateDesktopShortcut
  ${If} $NoShortcutMode != 1
    SetOutPath "$INSTDIR"
    CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARY}" "" "$INSTDIR\${MAINBINARY}" 0
  ${EndIf}
FunctionEnd

Function RunProgram
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\${MAINBINARY}"'
FunctionEnd

; The uninstaller's check box, placed on the confirm page the way Tauri's installers place theirs.
!define /ifndef WS_EX_LAYOUTRTL 0x00400000
Function un.ConfirmShow
  FindWindow $1 "#32770" "" $HWNDPARENT
  System::Call "user32::GetDpiForWindow(p r1) i .r2"
  ${If} $2 = 0
    StrCpy $2 96
  ${EndIf}
  IntOp $4 0 * $2
  IntOp $5 100 * $2
  IntOp $6 400 * $2
  IntOp $7 25 * $2
  IntOp $4 $4 / 96
  IntOp $5 $5 / 96
  IntOp $6 $6 / 96
  IntOp $7 $7 / 96
  System::Call 'user32::CreateWindowEx(i ${__NSD_CheckBox_EXSTYLE}, w "${__NSD_CheckBox_CLASS}", w "Also delete my saved reviews and settings", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $DeleteDataCheckbox
  SendMessage $HWNDPARENT ${WM_GETFONT} 0 0 $1
  SendMessage $DeleteDataCheckbox ${WM_SETFONT} $1 1
FunctionEnd

Function un.ConfirmLeave
  SendMessage $DeleteDataCheckbox ${BM_GETCHECK} 0 0 $DeleteDataState
FunctionEnd

; Deletes a shortcut only when it starts this copy's program, so a shortcut to another copy of PDF Remediator stays.
; (Shell link check as in Tauri's installers: IShellLink loaded through IPersistFile.)
!define /ifndef STGM_READ 0
!define /ifndef SLGP_RAWPATH 4
!macro DELETE_OUR_SHORTCUT shortcut
  ${If} ${FileExists} "${shortcut}"
    StrCpy $3 0
    !insertmacro ComHlpr_CreateInProcInstance ${CLSID_ShellLink} ${IID_IShellLink} r0 ""
    ${If} $0 P<> 0
      ${IUnknown::QueryInterface} $0 '("${IID_IPersistFile}", .r1)'
      ${If} $1 P<> 0
        ${IPersistFile::Load} $1 '("${shortcut}", ${STGM_READ})'
        ${IShellLink::GetPath} $0 '(.r2, ${NSIS_MAX_STRLEN}, 0, ${SLGP_RAWPATH})'
        ${If} $2 == "$INSTDIR\${MAINBINARY}"
          StrCpy $3 1
        ${EndIf}
        ${IUnknown::Release} $1 ""
      ${EndIf}
      ${IUnknown::Release} $0 ""
    ${EndIf}
    ${If} $3 = 1
      Delete "${shortcut}"
    ${EndIf}
  ${EndIf}
!macroend

; /DELETEDATA does what the "Also delete my saved reviews and settings" box does, for a silent uninstall (/S).
Function un.onInit
  ${un.GetOptions} $CMDLINE "/DELETEDATA" $0
  ${IfNot} ${Errors}
    StrCpy $DeleteDataState 1
  ${EndIf}
FunctionEnd

Section Uninstall
  !insertmacro WAIT_UNTIL_CLOSED

  Call un.IsOurInstallation
  !insertmacro REMOVE_PROGRAM
  Delete "$INSTDIR\uninstall.exe"
  ; Copies made before version 0.3.0 alpha 6 kept OCR's temporary files here; they now live under output and are removed after each run.
  RMDir /r "$INSTDIR\tmp"
  ${If} $DeleteDataState = 1
    RMDir /r "$INSTDIR\output"
  ${EndIf}
  ; Removed only when nothing is left in it, so saved reviews and anything else the person put there stay.
  RMDir "$INSTDIR"

  !insertmacro DELETE_OUR_SHORTCUT "$SMPROGRAMS\${PRODUCTNAME}.lnk"
  !insertmacro DELETE_OUR_SHORTCUT "$DESKTOP\${PRODUCTNAME}.lnk"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "${PRODUCTKEY}"
SectionEnd
