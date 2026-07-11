param(
    [switch]$SkipChecks,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ServerDir = Join-Path $Root "server"
$DesktopDir = Join-Path $Root "desktop"
$ReleaseDir = Join-Path $DesktopDir "release"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
}

function Assert-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Assert-ReleaseDir {
    $ResolvedDesktopDir = [System.IO.Path]::GetFullPath($DesktopDir)
    $ResolvedReleaseDir = [System.IO.Path]::GetFullPath($ReleaseDir)
    $ExpectedPrefix = $ResolvedDesktopDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

    if (-not $ResolvedReleaseDir.StartsWith($ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean unexpected release directory: $ResolvedReleaseDir"
    }

    if ((Split-Path -Leaf $ResolvedReleaseDir) -ne "release") {
        throw "Refusing to clean non-release directory: $ResolvedReleaseDir"
    }
}

function Remove-ReleaseDir {
    Assert-ReleaseDir

    if (Test-Path -LiteralPath $ReleaseDir) {
        Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
    }
}

function Remove-ReleaseClutter {
    Assert-ReleaseDir

    $ClutterNames = @(
        "win-unpacked",
        "runtime",
        "builder-debug.yml",
        "builder-effective-config.yaml"
    )

    foreach ($Name in $ClutterNames) {
        $Path = Join-Path $ReleaseDir $Name
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Recurse -Force
        }
    }
}

Push-Location $Root
try {
    Assert-Command "node"
    Assert-Command "npm"
    Assert-Command "uv"

    Invoke-Step "Prepare backend virtual environment" {
        Push-Location $ServerDir
        try {
            if (-not $SkipInstall) {
                uv sync
            }
        }
        finally {
            Pop-Location
        }
    }

    if (-not $SkipChecks) {
        Invoke-Step "Run backend tests" {
            Push-Location $ServerDir
            try {
                uv run python -m pytest -q
            }
            finally {
                Pop-Location
            }
        }

        Invoke-Step "Run backend lint" {
            Push-Location $ServerDir
            try {
                uv run python -m ruff check .
            }
            finally {
                Pop-Location
            }
        }
    }

    Invoke-Step "Prepare desktop dependencies" {
        Push-Location $DesktopDir
        try {
            if (-not $SkipInstall) {
                npm install
            }
        }
        finally {
            Pop-Location
        }
    }

    Invoke-Step "Clean previous Windows package output" {
        Remove-ReleaseDir
    }

    Invoke-Step "Build Windows portable exe" {
        Push-Location $DesktopDir
        try {
            npm run dist:win
        }
        finally {
            Pop-Location
        }
    }

    Invoke-Step "Remove packaging intermediate files" {
        Remove-ReleaseClutter
    }

    $Artifacts = Get-ChildItem -Path $ReleaseDir -Filter "*.exe" -File |
        Sort-Object LastWriteTime -Descending

    if (-not $Artifacts) {
        throw "Build finished but no .exe artifact was found in $ReleaseDir."
    }

    Write-Host ""
    Write-Host "Windows package created:" -ForegroundColor Green
    foreach ($Artifact in $Artifacts) {
        Write-Host $Artifact.FullName
    }
}
finally {
    Pop-Location
}
