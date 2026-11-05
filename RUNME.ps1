param(
    # Installs every declared tool that is missing, reports each one and exits.
    [switch]$Setup,
    # Lists the declared tools with their resolved paths and exits.
    [switch]$Tools
)

$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 turns redirected native stderr (uv progress, obs-html warnings) into
# error records; under "Stop" the first one would abort. Exit codes alone judge native commands.
function Invoke-Native([string]$Command, [string[]]$Arguments) {
    $ErrorActionPreference = "Continue"
    & $Command @Arguments
}

# Every tool a contributor or agent needs, declared once: each run installs uv, -Setup installs
# all of them, and scripts\new-worktree.ps1 checks the same list through -Tools.
$DeclaredTools = @(
    [pscustomobject]@{ Name = "uv"; WingetId = "astral-sh.uv"; Command = "uv"; Files = @() }
    [pscustomobject]@{ Name = "git"; WingetId = "Git.Git"; Command = "git"; Files = @() }
    [pscustomobject]@{ Name = "node"; WingetId = "OpenJS.NodeJS.LTS"; Command = "node"; Files = @() }
    [pscustomobject]@{ Name = "gh"; WingetId = "GitHub.cli"; Command = "gh"; Files = @() }
    [pscustomobject]@{ Name = "chrome"; WingetId = "Google.Chrome"; Command = $null; Files = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    ) }
)

function Find-Tool($Tool) {
    if ($Tool.Command) {
        $found = Get-Command $Tool.Command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.Source }
    }
    foreach ($file in $Tool.Files) {
        if (Test-Path -LiteralPath $file -PathType Node) { return $file }
    }
    return $null
}

function Install-Tool($Tool) {
    $winget = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        throw "winget is required to install $($Tool.Name) ($($Tool.WingetId)) on a bare Windows system."
    }
    Invoke-Native $winget.Source @("install", "--id", $Tool.WingetId, "--exact", "--accept-package-agreements", "--accept-source-agreements") | Out-Host
    $code = $LASTEXITCODE
    # winget records new PATH entries for the next terminal; pick them up in this one.
    $env:PATH = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine")
        [Environment]::GetEnvironmentVariable("Path", "User")
        $env:PATH
    ) -join ";"
    $path = Find-Tool $Tool
    if (-not $path) {
        throw "$($Tool.Name) is not available after 'winget install --id $($Tool.WingetId)' (exit $code). Start a new terminal and retry."
    }
    return $path
}

if (($Setup -or $Tools) -and $args.Count) {
    throw "-Setup and -Tools take no obs-html arguments."
}

if ($Tools) {
    # No exit here: it would drop the pending table formatting of a console run.
    foreach ($tool in $DeclaredTools) {
        [pscustomobject]@{ Name = $tool.Name; WingetId = $tool.WingetId; Path = Find-Tool $tool }
    }
} elseif ($Setup) {
    $missing = 0
    foreach ($tool in $DeclaredTools) {
        $path = Find-Tool $tool
        $state = "present"
        if (-not $path) {
            try {
                $path = Install-Tool $tool
                $state = "installed"
            } catch {
                Write-Host "$($tool.Name): MISSING - $($_.Exception.Message)"
                $missing++
                continue
            }
        }
        Write-Host "$($tool.Name): $state ($path)"
    }
    if ($missing) {
        Write-Host "$missing of $($DeclaredTools.Count) declared tools are missing."
        exit 1
    }
    Write-Host "All $($DeclaredTools.Count) declared tools are present."
    exit 0
} else {
    $UvTool = $DeclaredTools | Where-Object { $_.Name -eq "uv" }
    $Uv = Find-Tool $UvTool
    if (-not $Uv) {
        $Uv = Install-Tool $UvTool
    }

    Push-Location $PSScriptRoot
    try {
        Invoke-Native $Uv (@("run", "obs-html") + $args)
    } finally {
        Pop-Location
    }
    exit $LASTEXITCODE
}