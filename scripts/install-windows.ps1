param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path
$startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startup "Video Extensao Download.lnk"))
$shortcut.TargetPath = Join-Path $Root "run.bat"
$shortcut.WorkingDirectory = $Root
$shortcut.WindowStyle = 7
$shortcut.Save()

function Test-Health {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8734/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-Health)) {
    Start-Process -FilePath (Join-Path $Root "run.bat") -WorkingDirectory $Root -WindowStyle Minimized
    $ready = $false
    foreach ($unused in 1..90) {
        Start-Sleep -Seconds 1
        if (Test-Health) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        exit 1
    }
}

exit 0
