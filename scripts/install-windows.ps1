param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path
$HostName = "com.videoextensao.download"
# ExtensionId is the Chrome id derived from the key in extension/manifest.json.
$ExtensionId = "cgollnjfijlggoeoihnkddekmkambgel"
$FirefoxId = "video-extensao-download@local"
$Port = 8734
if ($env:MDE_PORT) { $Port = [int]$env:MDE_PORT }

$startup = [Environment]::GetFolderPath("Startup")
$oldShortcut = Join-Path $startup "Video Extensao Download.lnk"
if (Test-Path -LiteralPath $oldShortcut) {
    Remove-Item -LiteralPath $oldShortcut -Force
}

function Stop-DownloadHost {
    $escaped = [Regex]::Escape($Root)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and $_.CommandLine -match $escaped -and $_.CommandLine -match '-m host'
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Stop-DownloadHost
Start-Sleep -Milliseconds 400

$dir = Join-Path $env:LOCALAPPDATA "video-extensao-download"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$cmd = Join-Path $Root "scripts\ved-host.cmd"
$cmdJson = $cmd.Replace("\", "\\").Replace('"', '\"')
$utf8 = New-Object System.Text.UTF8Encoding $false

$chromeManifest = Join-Path $dir "chrome.json"
$firefoxManifest = Join-Path $dir "firefox.json"
[System.IO.File]::WriteAllText($chromeManifest, @"
{
  "name": "$HostName",
  "description": "Video Extensao Download",
  "path": "$cmdJson",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://${ExtensionId}/"]
}
"@, $utf8)
[System.IO.File]::WriteAllText($firefoxManifest, @"
{
  "name": "$HostName",
  "description": "Video Extensao Download",
  "path": "$cmdJson",
  "type": "stdio",
  "allowed_extensions": ["$FirefoxId"]
}
"@, $utf8)

function Register-Host([string]$Key, [string]$Manifest) {
    New-Item -Path $Key -Force | Out-Null
    Set-Item -Path $Key -Value $Manifest
}

foreach ($key in @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$HostName",
    "HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\$HostName",
    "HKCU:\Software\Chromium\NativeMessagingHosts\$HostName"
)) {
    Register-Host $key $chromeManifest
}
Register-Host "HKCU:\Software\Mozilla\NativeMessagingHosts\$HostName" $firefoxManifest

function Test-Health {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:${Port}/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = Join-Path $Root ".venv\Scripts\python.exe"
}
$previousIdle = $env:MDE_IDLE_EXIT
$env:MDE_IDLE_EXIT = "1"
$proc = Start-Process -FilePath $pythonw -ArgumentList "-m", "host" -WorkingDirectory $Root -WindowStyle Hidden -PassThru
$ready = $false
foreach ($unused in 1..60) {
    Start-Sleep -Milliseconds 500
    if (Test-Health) {
        $ready = $true
        break
    }
}
if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Stop-DownloadHost
if ($null -eq $previousIdle) {
    Remove-Item Env:MDE_IDLE_EXIT -ErrorAction SilentlyContinue
} else {
    $env:MDE_IDLE_EXIT = $previousIdle
}
if (-not $ready) {
    exit 1
}
exit 0
