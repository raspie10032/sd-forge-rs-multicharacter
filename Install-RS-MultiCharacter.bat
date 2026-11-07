@echo off
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
# Source for the standalone Install-RS-MultiCharacter.bat. Windows PowerShell 5.1 compatible.
param(
    [string]$ForgePath = $env:RS_MC_FORGE_PATH,
    [switch]$LibraryOnly
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:RsMcName = 'sd-forge-rs-multicharacter'
$script:RsMcRepository = 'raspie10032/sd-forge-rs-multicharacter'

function Resolve-RsMcForgePath([string]$Path) {
    $Path = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw 'Folder not found. Select the existing Forge Neo folder.'
    }
    $root = (Get-Item -LiteralPath $Path).FullName
    if (-not (Test-Path -LiteralPath (Join-Path $root 'launch.py') -PathType Leaf)) {
        $root = Join-Path $root 'webui'
    }
    foreach ($file in @('launch.py', 'webui.py', 'modules_forge/forge_version.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $file) -PathType Leaf)) {
            throw 'This is not a Forge Neo folder. Select the folder with launch.py (or its portable parent).'
        }
    }
    $version = Get-Content -LiteralPath (Join-Path $root 'modules_forge/forge_version.py') -Raw
    if ($version -notmatch '(?m)^\s*version\s*=\s*[''" ]*neo[''"]') {
        throw 'The selected host is not Forge Neo. Install Forge Neo first.'
    }
    return (Get-Item -LiteralPath $root).FullName
}

function Select-RsMcForgePath {
    $path = Read-Host 'Paste the Forge Neo folder path (Enter = folder picker)'
    if (-not [string]::IsNullOrWhiteSpace($path)) { return Resolve-RsMcForgePath $path }
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    try {
        $dialog.Description = 'Select Forge Neo (the folder with launch.py, or its portable parent)'
        $dialog.ShowNewFolderButton = $false
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            throw 'Installation cancelled. No files were changed.'
        }
        return Resolve-RsMcForgePath $dialog.SelectedPath
    } finally { $dialog.Dispose() }
}

function Assert-RsMcForgeStopped([string]$Root) {
    # A relative launch.py with an external Python gives no reliable target directory.
    # Conservatively ask the user to close that WebUI too; never kill a process.
    $running = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^(python(w)?|pypy[\d.]*)\.exe$' -and
        $_.CommandLine -and $_.CommandLine -match '(?i)(^|[\s"/\\])(launch|webui)\.py([\s"]|$)'
    })
    if ($running.Count) {
        $pids = ($running | ForEach-Object { $_.ProcessId }) -join ', '
        throw "A Forge/WebUI Python process is running (PID: $pids). Close its terminal/launcher, then run this installer again."
    }
}

function Assert-RsMcDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Expected a regular directory, not a file/link/junction: $Path"
        }
    }
}

function Get-RsMcRelease {
    $headers = @{ 'User-Agent' = 'RS-MultiCharacter-Windows-Installer'; 'Accept' = 'application/vnd.github+json' }
    # /latest excludes prereleases; the project currently publishes alpha releases.
    $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$script:RsMcRepository/releases?per_page=100" -Headers $headers
    foreach ($release in @($releases | Where-Object { -not $_.draft } | Sort-Object published_at -Descending)) {
        $zip = @($release.assets | Where-Object { $_.name -match '^sd-forge-rs-multicharacter-[0-9][\w.\-]*\.zip$' })
        $sums = @($release.assets | Where-Object { $_.name -eq 'SHA256SUMS' })
        if ($zip.Count -eq 1 -and $sums.Count -eq 1) {
            return [pscustomobject]@{ Tag = $release.tag_name; Zip = $zip[0]; Sums = $sums[0] }
        }
    }
    throw 'No published installable release found on GitHub. Retry later or use the manual ZIP method.'
}

function Save-RsMcDownload([string]$Url, [string]$Destination) {
    if ($Url -notmatch '^https://github\.com/raspie10032/sd-forge-rs-multicharacter/releases/download/') {
        throw 'Unexpected release download URL.'
    }
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -Headers @{
        'User-Agent' = 'RS-MultiCharacter-Windows-Installer'
    }
}

function Assert-RsMcChecksum([string]$Archive, [string]$Checksums, [string]$AssetName) {
    $lines = @(Get-Content -LiteralPath $Checksums | Where-Object {
        $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($AssetName) + '$')
    })
    if ($lines.Count -ne 1) { throw 'SHA256SUMS does not identify exactly one matching release ZIP.' }
    $expected = ($lines[0] -split '\s+')[0]
    $actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
    if ($actual -ne $expected) { throw 'Release ZIP checksum mismatch. Nothing was installed. Retry the download.' }
}

function Expand-RsMcArchive([string]$Archive, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        [long]$total = 0
        if ($zip.Entries.Count -gt 10000) { throw 'Release ZIP contains too many files.' }
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            $parts = $name.TrimEnd('/').Split('/')
            if ($name.StartsWith('/') -or $name.Contains(':') -or $parts -contains '..' -or
                $parts -contains '.' -or $parts -contains '' -or -not $seen.Add($name)) {
                throw 'Unsafe or duplicate path in release ZIP.'
            }
            foreach ($part in $parts) {
                if ($part -match '[<>"|?*\x00-\x1f]' -or $part -match '[. ]$' -or
                    $part -match '^(?i:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\.|$)') {
                    throw 'Invalid Windows path in release ZIP.'
                }
            }
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {
                throw 'Links are not allowed in the release ZIP.'
            }
            $total += $entry.Length
            if ($total -gt 536870912) { throw 'Release ZIP is larger than the installer limit.' }
        }
    } finally { $zip.Dispose() }
    # ZipFile takes a literal path, unlike Expand-Archive's DestinationPath on PS 5.1.
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
    $payload = Join-Path $Destination $script:RsMcName
    foreach ($file in @('scripts/rs_multicharacter.py', 'rs_forge_mc/config.py',
                         'javascript/rs_multicharacter.js', 'pyproject.toml', 'COPYING')) {
        if (-not (Test-Path -LiteralPath (Join-Path $payload $file) -PathType Leaf)) {
            throw "Invalid release layout: missing $file. Nothing was installed."
        }
    }
    return $payload
}

function Install-RsMcPayload([string]$Root, [string]$Payload) {
    $extensions = Join-Path $Root 'extensions'
    $backupRoot = Join-Path $Root '.rs-mc-backups'
    $target = Join-Path $extensions $script:RsMcName
    foreach ($path in @($extensions, $backupRoot, $target)) { Assert-RsMcDirectory $path }
    [IO.Directory]::CreateDirectory($extensions) | Out-Null
    $backup = $null
    if (Test-Path -LiteralPath $target) {
        [IO.Directory]::CreateDirectory($backupRoot) | Out-Null
        $backup = Join-Path $backupRoot ($script:RsMcName + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        Move-Item -LiteralPath $target -Destination $backup
    }
    try {
        Move-Item -LiteralPath $Payload -Destination $target
    } catch {
        $failure = $_
        if ($backup -and -not (Test-Path -LiteralPath $target)) {
            Move-Item -LiteralPath $backup -Destination $target
        }
        throw $failure
    }
    return [pscustomobject]@{ Target = $target; Backup = $backup }
}

if ($LibraryOnly) { return }

$work = $null
try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'Run Install-RS-MultiCharacter.bat on Windows. Linux: use URL/Git/ZIP installation.'
    }
    Write-Host ''
    Write-Host 'RS MultiCharacter for Forge Neo - Windows installer' -ForegroundColor Cyan
    Write-Host 'Close Forge Neo and its launcher before continuing.'
    Write-Host 'Installs the latest published release, including alpha releases. No Git required.'
    Write-Host 'Existing extension files are backed up outside extensions. Models/settings are kept.'
    Write-Host ''
    if ([string]::IsNullOrWhiteSpace($ForgePath)) { $root = Select-RsMcForgePath }
    else { $root = Resolve-RsMcForgePath $ForgePath }
    Write-Host "Forge Neo: $root"
    Assert-RsMcForgeStopped $root
    foreach ($path in @($root, (Join-Path $root 'extensions'), (Join-Path $root '.rs-mc-backups'),
                         (Join-Path $root "extensions/$script:RsMcName"))) { Assert-RsMcDirectory $path }

    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $release = Get-RsMcRelease
    Write-Host "Downloading $($release.Tag)..."
    # Same volume as the target: only rename directories when committing the install.
    $work = Join-Path $root ('.rs-mc-install-' + [guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($work) | Out-Null
    $archive = Join-Path $work 'release.zip'
    $checksums = Join-Path $work 'SHA256SUMS'
    Save-RsMcDownload $release.Zip.browser_download_url $archive
    Save-RsMcDownload $release.Sums.browser_download_url $checksums
    Assert-RsMcChecksum $archive $checksums $release.Zip.name
    Write-Host 'SHA-256 verified. Checking and extracting release...'
    $payload = Expand-RsMcArchive $archive (Join-Path $work 'unpacked')
    Assert-RsMcForgeStopped $root
    $result = Install-RsMcPayload $root $payload
    Write-Host ''
    Write-Host "Installed $($release.Tag): $($result.Target)" -ForegroundColor Green
    if ($result.Backup) { Write-Host "Previous extension backup: $($result.Backup)" }
    Write-Host 'This is a release/ZIP installation. Run this BAT again for future updates.'
    Write-Host 'The previous Git checkout, if any, is in the backup. WebUI Git updates do not apply.'
    Write-Host 'Start Forge Neo with your usual launcher, then hard-refresh the browser (Ctrl+Shift+R).'
    Write-Host 'Look for: RS MultiCharacter (txt2img / img2img).'
    Write-Host 'Basic sampling is ready. Optional feature packages and weights are not installed by this BAT.'
    Write-Host 'Guide: https://github.com/raspie10032/sd-forge-rs-multicharacter/blob/main/docs/user-guide.md#models'
} catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.InvocationInfo.PositionMessage
    Write-Host 'The installer does not change Forge launch options, Python packages, models or GPU selection.'
    exit 1
} finally {
    if ($work -and (Test-Path -LiteralPath $work)) {
        try { Remove-Item -LiteralPath $work -Recurse -Force }
        catch { Write-Warning "Temporary files remain at: $work" }
    }
}
exit 0
