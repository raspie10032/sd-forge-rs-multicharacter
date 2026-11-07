param([switch]$Online)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$repository = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'windows-installer.ps1') -LibraryOnly
$script:Checks = 0

function Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAILED: $Message" }
    $script:Checks++
    Write-Host "PASS: $Message"
}

function Must-Fail([scriptblock]$Action, [string]$Pattern, [string]$Message) {
    $failure = $null
    try { & $Action | Out-Null } catch { $failure = $_.Exception.Message }
    Check ($null -ne $failure -and $failure -match $Pattern) $Message
}

function Write-FixtureFile([string]$Path, [string]$Content = 'fixture') {
    [IO.Directory]::CreateDirectory((Split-Path $Path -Parent)) | Out-Null
    [IO.File]::WriteAllText($Path, $Content)
}

function New-Forge([string]$Root) {
    foreach ($file in @('launch.py', 'webui.py')) { Write-FixtureFile (Join-Path $Root $file) }
    Write-FixtureFile (Join-Path $Root 'modules_forge/forge_version.py') 'version = "neo"'
    return $Root
}

function New-ReleaseZip([string]$Path, [hashtable]$Entries) {
    $zip = [IO.Compression.ZipFile]::Open($Path, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($name in $Entries.Keys) {
            $entry = $zip.CreateEntry($name)
            $writer = New-Object IO.StreamWriter ($entry.Open())
            try { $writer.Write($Entries[$name]) } finally { $writer.Dispose() }
        }
    } finally { $zip.Dispose() }
}

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
$temp = Join-Path ([IO.Path]::GetTempPath()) ('rs-mc-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
[IO.Directory]::CreateDirectory($temp) | Out-Null
try {
    $errorsFound = $null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'windows-installer.ps1'),
        [ref]$null, [ref]$errorsFound) | Out-Null
    Check ($errorsFound.Count -eq 0) 'PowerShell source parses'
    $batch = [IO.File]::ReadAllText((Join-Path $repository 'Install-RS-MultiCharacter.bat'))
    $marker = '#' + ' RS_MC_POWERSHELL_BEGIN'
    $payloadText = $batch.Substring($batch.IndexOf($marker) + $marker.Length).Trim()
    $sourceText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'windows-installer.ps1')).Trim()
    Check ($payloadText.Replace("`r`n", "`n") -ceq $sourceText.Replace("`r`n", "`n")) 'Standalone BAT embeds the exact source'

    # Invoke-RestMethod writes a JSON root array as one pipeline object on PS 5.1/7.
    # Include a newer asset-less release and a draft to check usable-alpha selection.
    function Invoke-RestMethod {
        $assets = @([pscustomobject]@{ name = 'sd-forge-rs-multicharacter-0.2.0a2.zip' },
                    [pscustomobject]@{ name = 'SHA256SUMS' })
        return ,@(
            [pscustomobject]@{ draft = $false; tag_name = 'empty'; published_at = '2026-11-10'; assets = @() },
            [pscustomobject]@{ draft = $true; tag_name = 'draft'; published_at = '2026-11-09'; assets = $assets },
            [pscustomobject]@{ draft = $false; tag_name = 'v0.2.0a2'; published_at = '2026-11-08'; assets = $assets },
            [pscustomobject]@{ draft = $false; tag_name = 'v0.1.0'; published_at = '2026-11-07'; assets = $assets }
        )
    }
    try {
        Check ((Get-RsMcRelease).Tag -eq 'v0.2.0a2') 'Selects the newest usable published alpha from an API array'
    } finally { Remove-Item Function:\Invoke-RestMethod }

    # Build non-ASCII paths without relying on PS 5.1 source-file encoding.
    $unicode = [string][char]0xD55C + [char]0x65E5 + [char]0x4E2D
    $root = New-Forge (Join-Path $temp ("Forge [x] ! & ' (" + $unicode + ')'))
    Check ((Resolve-RsMcForgePath ('"' + $root + '"')) -eq $root) 'Quoted, Unicode, spaces and shell punctuation in Forge path'
    $portable = Join-Path $temp 'portable'
    $inner = New-Forge (Join-Path $portable 'webui')
    Check ((Resolve-RsMcForgePath $portable) -eq $inner) 'Portable parent resolves to webui'
    Must-Fail { Resolve-RsMcForgePath $temp } 'not a Forge Neo' 'Rejects the wrong folder'
    Write-FixtureFile (Join-Path $inner 'modules_forge/forge_version.py') 'version = "classic"'
    Must-Fail { Resolve-RsMcForgePath $inner } 'not Forge Neo' 'Rejects a non-Neo host'

    $entries = @{}
    foreach ($file in @('scripts/rs_multicharacter.py', 'rs_forge_mc/config.py',
                         'javascript/rs_multicharacter.js', 'pyproject.toml', 'COPYING')) {
        $entries["sd-forge-rs-multicharacter/$file"] = 'new release'
    }
    $archive = Join-Path $temp 'release.zip'
    New-ReleaseZip $archive $entries
    $sums = Join-Path $temp 'SHA256SUMS'
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    Write-FixtureFile $sums ($hash + '  release.zip')
    Assert-RsMcChecksum $archive $sums 'release.zip'
    Check $true 'Accepts the matching SHA-256'
    Write-FixtureFile $sums (('0' * 64) + '  release.zip')
    Must-Fail { Assert-RsMcChecksum $archive $sums 'release.zip' } 'checksum mismatch' 'Rejects a corrupted download'
    Write-FixtureFile $sums ($hash + '  other.zip')
    Must-Fail { Assert-RsMcChecksum $archive $sums 'release.zip' } 'exactly one' 'Rejects missing checksum entry'
    Must-Fail { Save-RsMcDownload 'https://example.org/evil.zip' (Join-Path $temp 'evil.zip') } 'Unexpected release' 'Rejects an unrelated download URL'

    foreach ($name in @('../escape.py', '/absolute.py', 'C:/drive.py', 'a/../../escape.py',
                         'a\..\escape.py', 'a/NUL.txt', 'a/trailing.')) {
        $unsafe = Join-Path $temp ('bad-' + [guid]::NewGuid().ToString('N') + '.zip')
        New-ReleaseZip $unsafe @{ $name = 'unsafe' }
        Must-Fail { Expand-RsMcArchive $unsafe (Join-Path $temp 'unsafe') } 'path in release ZIP' "Rejects unsafe ZIP entry: $name"
    }
    $badLayout = Join-Path $temp 'missing.zip'
    New-ReleaseZip $badLayout @{ 'random/README.md' = 'not the release' }
    Must-Fail { Expand-RsMcArchive $badLayout (Join-Path $temp 'missing') } 'Invalid release layout' 'Rejects an incomplete release'

    # Real file moves: new install, update/backup, and rollback after a failed commit.
    Write-FixtureFile (Join-Path $root 'config.json') 'personal Forge settings'
    Write-FixtureFile (Join-Path $root 'models/rs_mc/assets/reference.png') 'reference data'
    Write-FixtureFile (Join-Path $root 'models/rs_pose3d/personal.json') 'pose data'
    Write-FixtureFile (Join-Path $root 'extensions/another-extension/keep.txt') 'other extension'
    $payload = Expand-RsMcArchive $archive (Join-Path $temp 'first')
    $installed = Install-RsMcPayload $root $payload
    Check (-not $installed.Backup -and (Test-Path -LiteralPath (Join-Path $installed.Target 'scripts/rs_multicharacter.py'))) 'New installation at the correct extension depth'
    Write-FixtureFile (Join-Path $installed.Target 'personal.txt') 'manual changes'
    Write-FixtureFile (Join-Path $installed.Target '.git/config') 'old Git data'
    $payload = Expand-RsMcArchive $archive (Join-Path $temp 'second')
    $updated = Install-RsMcPayload $root $payload
    Check ((Test-Path -LiteralPath (Join-Path $updated.Backup 'personal.txt')) -and
           (Test-Path -LiteralPath (Join-Path $updated.Backup '.git/config'))) 'Update preserves the entire old extension and Git data in backup'
    Check (-not (Test-Path -LiteralPath (Join-Path $root 'extensions/.rs-mc-backups'))) 'Backup lives outside the extension loader'
    foreach ($file in @('config.json', 'models/rs_mc/assets/reference.png', 'models/rs_pose3d/personal.json',
                         'extensions/another-extension/keep.txt')) {
        Check ((Get-Content -LiteralPath (Join-Path $root $file) -Raw) -match 'personal|reference|pose|other') "Preserves $file"
    }
    Must-Fail { Install-RsMcPayload $root (Join-Path $temp 'nonexistent-payload') } 'not exist|Cannot find' 'Failed replacement reports an error'
    Check ((Get-Content -LiteralPath (Join-Path $installed.Target 'scripts/rs_multicharacter.py') -Raw) -eq 'new release') 'Failed replacement rolls the previous extension back'

    # Simulate Windows process inventory without starting or terminating applications.
    function Get-CimInstance {
        param($ClassName, $ErrorAction)
        return $script:ProcessFixture
    }
    $script:ProcessFixture = @([pscustomobject]@{ Name = 'python.exe'; ProcessId = 12; CommandLine = 'python.exe main.py' })
    Assert-RsMcForgeStopped $root
    Check $true 'ComfyUI main.py does not block installation'
    foreach ($command in @('python.exe launch.py --port 7862', 'python.exe "D:\Forge Neo\webui.py"',
                            'python.exe "D:/Forge Neo/launch.py"')) {
        $script:ProcessFixture = @([pscustomobject]@{ Name = 'python.exe'; ProcessId = 42; CommandLine = $command })
        Must-Fail { Assert-RsMcForgeStopped $root } 'PID: 42' "Detects running WebUI: $command"
    }
    Remove-Item Function:\Get-CimInstance

    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $env:RS_MC_NO_PAUSE = '1'
        $bat = Join-Path $repository 'Install-RS-MultiCharacter.bat'
        $invalid = Join-Path $temp "missing ! & ' [x]"
        & $bat $invalid
        Check ($LASTEXITCODE -eq 1) 'Actual CMD-to-PowerShell BAT propagates failure without path injection'
        if ($Online) {
            # Real GitHub download + checksum + extraction + commit via the shipped BAT.
            # This fixture is a directory, NOT a Forge instance or GPU generation test.
            & $bat $root
            Check ($LASTEXITCODE -eq 0) 'Standalone BAT online installation on Windows PowerShell 5.1'
            Check ((Get-Content -LiteralPath (Join-Path $installed.Target 'pyproject.toml') -Raw) -match 'sd-forge-rs-multicharacter') 'Online install downloaded a real release'
            Check (-not @(Get-ChildItem -LiteralPath $root -Directory -Force | Where-Object { $_.Name -like '.rs-mc-install-*' }).Count) 'Temporary download/extraction directories are cleaned up'
            # A real running Python is represented by a harmless python.exe fixture
            # launched with a launch.py filename; no Forge or GPU is started.
            $dummy = Join-Path $temp 'launch.py'
            Write-FixtureFile $dummy 'import time; time.sleep(60)'
            $python = (Get-Command python.exe).Source
            $process = Start-Process -FilePath $python -ArgumentList ('"' + $dummy + '"') -PassThru -WindowStyle Hidden
            try {
                & $bat $root
                Check ($LASTEXITCODE -eq 1) 'Actual running WebUI-shaped Python blocks the BAT'
            } finally { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
        }
    }
    Write-Host "All $script:Checks installer checks passed."
} finally {
    Remove-Item Env:\RS_MC_NO_PAUSE -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temp -Recurse -Force
}
