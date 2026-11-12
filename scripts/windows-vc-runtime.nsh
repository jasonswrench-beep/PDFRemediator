; Included by windows-installer.nsi (and by a test). Needs MINVC defined, and LogicLib, WordFunc and x64 included.
;
; The package does not carry Microsoft's Visual C++ runtime files (Microsoft limits who may pass them on). The programs in it use the
; copy Microsoft's own free Redistributable puts in the Windows system folder. CheckVcRuntime sets $R9 to "" when that copy is there and
; new enough, otherwise to what is missing: the same check as the program's own (windows-vc-runtime.cs).

!macro VC_FILE name
  ${If} $R9 == ""
    ${IfNot} ${FileExists} "$SYSDIR\${name}"
      StrCpy $R9 "${name} is missing."
    ${Else}
      GetDLLVersion "$SYSDIR\${name}" $R0 $R1
      IntOp $R2 $R0 >>> 16
      IntOp $R3 $R0 & 0xFFFF
      IntOp $R4 $R1 >>> 16
      IntOp $R5 $R1 & 0xFFFF
      ${VersionCompare} "$R2.$R3.$R4.$R5" "${MINVC}" $R6
      ${If} $R6 = 2
        StrCpy $R9 "${name} is version $R2.$R3.$R4.$R5, which is older than ${MINVC}."
      ${EndIf}
    ${EndIf}
  ${EndIf}
!macroend

Function CheckVcRuntime
  StrCpy $R9 ""
  ; The setup program is 32-bit: without this, Windows would show it the 32-bit system folder instead of the 64-bit one.
  ${DisableX64FSRedirection}
  ${IfNot} ${FileExists} "$SYSDIR\ucrtbase.dll"
    StrCpy $R9 "The Windows C runtime (ucrtbase.dll) is missing. Update Windows."
  ${EndIf}
  !insertmacro VC_FILE "vcruntime140.dll"
  !insertmacro VC_FILE "vcruntime140_1.dll"
  !insertmacro VC_FILE "msvcp140.dll"
  ${EnableX64FSRedirection}
FunctionEnd
