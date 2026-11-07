"""Build the single-file Windows installer without a downloaded script dependency."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = r'''@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Generated from tools/windows-installer.ps1; download this BAT and run it directly.
set "RS_MC_INSTALLER_FILE=%~f0"
set "RS_MC_FORGE_PATH=%~1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$raw=[IO.File]::ReadAllText($env:RS_MC_INSTALLER_FILE); $marker='#'+' RS_MC_POWERSHELL_BEGIN'; $start=$raw.IndexOf($marker); if($start -lt 0){exit 1}; & ([scriptblock]::Create($raw.Substring($start+$marker.Length)))"
set "RS_MC_EXIT=%ERRORLEVEL%"
echo.
if not defined RS_MC_NO_PAUSE pause
exit /b %RS_MC_EXIT%
# RS_MC_POWERSHELL_BEGIN
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the shipped BAT needs rebuilding")
    args = parser.parse_args()
    source = (ROOT / "tools/windows-installer.ps1").read_text(encoding="utf-8")
    data = (HEADER + source).replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii")
    output = ROOT / "Install-RS-MultiCharacter.bat"
    if args.check:
        if not output.exists() or output.read_bytes() != data:
            raise SystemExit("Run python tools/build_windows_installer.py and commit the generated BAT")
        print("Standalone BAT matches PowerShell source (ASCII, CRLF).")
    else:
        output.write_bytes(data)
        print(output.name)


if __name__ == "__main__":
    main()
