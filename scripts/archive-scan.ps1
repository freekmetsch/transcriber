<#
.SYNOPSIS
    Canonical feature-list archive scan. Single source of truth for the
    lifecycle invariant defined in second-brain/wiki/concepts/feature-list-lifecycle.md.

.DESCRIPTION
    For every active feature list (docs/feature-lists/*.md, excluding the archive/
    subfolder) whose first _Status: line is a terminal state (Shipped | Superseded |
    Cancelled), git-mv the file into docs/feature-lists/archive/. Then move any HTML
    artifact in docs/artifacts/ that is linked to a just-archived feature list (by
    derived slug) into docs/artifacts/archive/.

    Commands (/run, /update, /wrap, /done) INVOKE this script; they must never
    re-describe the scan logic inline. That prose-duplication is exactly what drifted
    update.md (**Status**: shipped) away from the canonical _Status: regex.

    Requires PowerShell (pwsh). No bash shim — the agent runs this directly via the
    PowerShell tool during /run, /wrap, /update, /done. No git hook invokes it.

.PARAMETER DryRun
    List what would move; move nothing. git mv is not executed.

.PARAMETER SweepOrphans
    Also archive HTML artifacts that match no active feature list AND are not
    referenced by any file under docs/ (guards ADR-linked artifacts). Default off
    because an unguarded orphan sweep can wrongly archive standalone ADR artifacts.
#>
Param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$DryRun,
    [switch]$SweepOrphans
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $RepoRoot

$featureDir = "docs/feature-lists"
$featureArchive = "docs/feature-lists/archive"
$artifactDir = "docs/artifacts"
$artifactArchive = "docs/artifacts/archive"

$terminalRegex = '^_Status:\s+(Shipped|Superseded|Cancelled)\b'
$statusRegex = '^_Status:'

$movedLists = New-Object System.Collections.Generic.List[string]
$movedHtml = New-Object System.Collections.Generic.List[string]

function Move-Tracked {
    Param([string]$From, [string]$To)
    if ($DryRun) { return }
    $destDir = Split-Path -Parent $To
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    # git mv preserves history; fall back to a plain move if the file is untracked.
    $null = git mv -- $From $To 2>&1
    if ($LASTEXITCODE -ne 0) {
        Move-Item -LiteralPath $From -Destination $To -Force
    }
}

# Returns the first _Status: line's terminal state, or $null if not terminal / absent.
function Get-TerminalState {
    Param([string]$Path)
    $lines = Get-Content -LiteralPath $Path
    foreach ($line in $lines) {
        if ($line -match $statusRegex) {
            if ($line -match "(?i)$terminalRegex") {
                return ($Matches[1])
            }
            return $null  # first _Status: line is active; do not scan later lines
        }
    }
    return $null
}

# slug: FEATURE_LIST_COMMAND_SYSTEM.md -> command-system
function Get-Slug {
    Param([string]$FileName)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    $base = $base -replace '^FEATURE_LIST_', ''
    return $base.ToLowerInvariant() -replace '_', '-'
}

# basename of an artifact with a leading YYYY-MM-DD- date prefix stripped
function Get-ArtifactStem {
    Param([string]$FileName)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    return ($base -replace '^\d{4}-\d{2}-\d{2}-', '')
}

if (-not (Test-Path $featureDir)) {
    Write-Host "archive-scan: no $featureDir in this repo, nothing to scan."
    exit 0
}

# 1) Archive terminal feature lists.
$activeLists = Get-ChildItem $featureDir -File -Filter "*.md" -ErrorAction SilentlyContinue
$archivedSlugs = New-Object System.Collections.Generic.List[string]

foreach ($file in $activeLists) {
    $state = Get-TerminalState $file.FullName
    if ($null -ne $state) {
        $dest = Join-Path $featureArchive $file.Name
        Move-Tracked -From "$featureDir/$($file.Name)" -To "$featureArchive/$($file.Name)"
        $movedLists.Add("$($file.Name) [$state]")
        $archivedSlugs.Add((Get-Slug $file.Name))
    }
}

# 2) Move HTML artifacts linked to a just-archived feature list.
if (Test-Path $artifactDir) {
    $artifactTypes = @('plan', 'harden', 'critique', 'diag')
    $activeHtml = Get-ChildItem $artifactDir -File -Filter "*.html" -ErrorAction SilentlyContinue

    foreach ($html in $activeHtml) {
        $stem = Get-ArtifactStem $html.Name
        $linked = $false
        foreach ($slug in $archivedSlugs) {
            if ($stem -eq $slug) { $linked = $true; break }
            foreach ($t in $artifactTypes) {
                if ($stem -eq "$t-$slug") { $linked = $true; break }
            }
            if ($linked) { break }
        }
        if ($linked) {
            Move-Tracked -From "$artifactDir/$($html.Name)" -To "$artifactArchive/$($html.Name)"
            $movedHtml.Add($html.Name)
        }
    }

    # 3) Optional guarded orphan sweep (default off).
    if ($SweepOrphans) {
        $activeSlugs = @{}
        foreach ($f in (Get-ChildItem $featureDir -File -Filter "*.md" -ErrorAction SilentlyContinue)) {
            $activeSlugs[(Get-Slug $f.Name)] = $true
        }
        $remainingHtml = Get-ChildItem $artifactDir -File -Filter "*.html" -ErrorAction SilentlyContinue
        foreach ($html in $remainingHtml) {
            $stem = Get-ArtifactStem $html.Name
            $matchesActive = $false
            foreach ($slug in $activeSlugs.Keys) {
                if ($stem -eq $slug -or $stem -match "^(plan|harden|critique|diag)-$([regex]::Escape($slug))$") {
                    $matchesActive = $true; break
                }
            }
            if ($matchesActive) { continue }
            # Guard: keep if any file under docs/ references this artifact (e.g. an ADR link).
            $referenced = $false
            $refHits = Get-ChildItem "docs" -Recurse -File -Filter "*.md" -ErrorAction SilentlyContinue |
                Select-String -SimpleMatch -Pattern $html.Name -List -ErrorAction SilentlyContinue
            if ($refHits) { $referenced = $true }
            if (-not $referenced) {
                Move-Tracked -From "$artifactDir/$($html.Name)" -To "$artifactArchive/$($html.Name)"
                $movedHtml.Add("$($html.Name) (orphan)")
            }
        }
    }
}

$prefix = if ($DryRun) { "archive-scan (DRY RUN)" } else { "archive-scan" }
Write-Host "${prefix}: feature-lists=$($movedLists.Count) htmls=$($movedHtml.Count)"
if ($movedLists.Count -gt 0) {
    foreach ($m in $movedLists) { Write-Host "  feature-list -> archive: $m" }
}
if ($movedHtml.Count -gt 0) {
    foreach ($m in $movedHtml) { Write-Host "  artifact -> archive:     $m" }
}
if ($movedLists.Count -eq 0 -and $movedHtml.Count -eq 0) {
    Write-Host "  nothing to archive."
}
exit 0
