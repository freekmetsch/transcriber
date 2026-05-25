<#
.SYNOPSIS
    Portable feature-list lifecycle lint. The cross-repo subset of truecolours
    docs-lint.ps1 — the _Status: invariant + lane consistency + a staged-only gate.

.DESCRIPTION
    PORTABLE INVARIANT CONTRACT (this is the canonical sibling-export source; copy
    verbatim into <repo>/scripts/feature-list-lint.ps1, do not re-derive):

      Vocabulary  - active states: Plan ready | In flight | Deferred
                    terminal states: Shipped | Superseded | Cancelled
                    Canonical spec: second-brain/wiki/concepts/feature-list-lifecycle.md
      Placement   - every active feature list (docs/feature-lists/*.md, excluding the
                    archive/ subfolder) must carry a _Status: line as the FIRST
                    non-blank line directly under its H1.
      Lane rule   - a terminal state in the active lane is an error (run
                    scripts/archive-scan.ps1 to git-mv it into archive/). A file may
                    never appear in both the active lane and the archive lane.
      Staged-only - with -StagedOnly, validate the invariant against STAGED feature
                    lists only (git diff --cached) and exit. Used by /done and any
                    pre-commit gate so pre-existing legacy debt in unrelated files
                    cannot block an otherwise-clean commit.

    This is the PORTABLE subset only. It deliberately omits truecolours-specific
    checks (forbidden stale-paths, full-repo broken-link sweep, command-mention
    integrity, known_issues lane checks) — those false-positive on unrelated
    pre-existing debt in structurally-different sibling repos. See truecolours
    ADR 0032 for the cross-repo rationale and ADR 0029 for the parent decision.

    Requires PowerShell (pwsh). No bash shim — the agent runs this directly via the
    PowerShell tool during /update and /done. No git hook invokes it.

.PARAMETER StagedOnly
    Validate the _Status: invariant against staged feature lists only, then exit.
#>
Param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$StagedOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $RepoRoot

$featureDir = "docs/feature-lists"
$featureArchive = "docs/feature-lists/archive"

# Guard: repos without a feature-list dir are a clean no-op (not a crash).
if (-not (Test-Path $featureDir)) {
    Write-Host "feature-list-lint: no $featureDir in this repo, nothing to lint." -ForegroundColor Green
    exit 0
}

$errors = New-Object System.Collections.Generic.List[string]

function Add-Error {
    Param([string]$Message)
    $errors.Add($Message)
}

# ---- Feature-list _Status: invariant (ADR 0029) ----
# Canonical vocabulary: second-brain/wiki/concepts/feature-list-lifecycle.md
$statusActiveStates = @('Plan ready', 'In flight', 'Deferred')
$statusTerminalStates = @('Shipped', 'Superseded', 'Cancelled')
$statusAllStates = $statusActiveStates + $statusTerminalStates
$statusVocabHint = "valid states: " + ($statusAllStates -join ' | ')

function Test-StatusInvariant {
    Param([string]$Path)
    # Validates one active-lane feature list. Adds errors for: no H1; no _Status:
    # line directly under the H1; state outside the controlled vocabulary; or a
    # terminal state still sitting in the active lane (should be archived).
    $lines = @(Get-Content -LiteralPath $Path)

    $h1Index = -1
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match '^#\s+\S') { $h1Index = $i; break }
    }
    if ($h1Index -lt 0) {
        Add-Error ("{0}: no H1 heading found (expected '# FEATURE_LIST_<NAME>')" -f $Path)
        return
    }

    # First non-blank line after the H1 must be the _Status: line.
    $statusLine = $null
    for ($i = $h1Index + 1; $i -lt $lines.Length; $i++) {
        if ($lines[$i].Trim() -eq '') { continue }
        $statusLine = $lines[$i]
        break
    }

    if ($null -eq $statusLine -or $statusLine -notmatch '^_Status:') {
        Add-Error ("{0}: missing '_Status:' line directly under the H1. Expected '_Status: <state> - <YYYY-MM-DD> (<note>)_'; {1}" -f $Path, $statusVocabHint)
        return
    }

    $statePattern = '^_Status:\s+(' + (($statusAllStates | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\b'
    if ($statusLine -notmatch "(?i)$statePattern") {
        Add-Error ("{0}: '_Status:' state not in the controlled vocabulary. Line: '{1}'. {2}" -f $Path, $statusLine.Trim(), $statusVocabHint)
        return
    }

    $matchedState = $Matches[1]
    $isTerminal = $statusTerminalStates | Where-Object { $_ -ieq $matchedState }
    if ($isTerminal) {
        Add-Error ("{0}: terminal state '{1}' is in the active lane - run 'scripts/archive-scan.ps1' to move it into docs/feature-lists/archive/" -f $Path, $matchedState)
    }
}

# Resolve the set of active-lane feature lists to validate.
function Get-ActiveFeatureListPaths {
    Param([switch]$Staged)
    if ($Staged) {
        $stagedRaw = @(git diff --cached --name-only --diff-filter=ACMR 2>$null)
        return $stagedRaw | Where-Object {
            $_ -match '^docs/feature-lists/[^/]+\.md$'
        } | ForEach-Object { Join-Path $RepoRoot $_ } | Where-Object { Test-Path $_ }
    }
    $active = Get-ChildItem $featureDir -File -Filter "*.md" -ErrorAction SilentlyContinue
    return $active | ForEach-Object { $_.FullName }
}

# Staged-only gate: validate the invariant on staged feature lists, then exit.
if ($StagedOnly) {
    $targets = @(Get-ActiveFeatureListPaths -Staged)
    foreach ($p in $targets) { Test-StatusInvariant $p }
    if ($errors.Count -gt 0) {
        Write-Host ""
        Write-Host "feature-list-lint (staged _Status: gate) failed with $($errors.Count) issue(s):" -ForegroundColor Red
        foreach ($e in $errors) { Write-Host "- $e" }
        Write-Host ""
        Write-Host "Fix the _Status: line (directly under the H1), then re-stage. $statusVocabHint" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "feature-list-lint staged _Status: gate passed ($($targets.Count) feature list(s) checked)." -ForegroundColor Green
    exit 0
}

# Lane consistency: a file must never appear in both active and archive lanes.
# Guard: a missing archive/ subfolder is fine (no archived files yet) — no throw.
$activeFeatureLists = Get-ChildItem $featureDir -File -Filter "*.md" -ErrorAction SilentlyContinue
$archivedFeatureLists = Get-ChildItem $featureArchive -File -Filter "*.md" -ErrorAction SilentlyContinue
$activeFeatureNames = @{}

foreach ($file in $activeFeatureLists) {
    $activeFeatureNames[$file.Name.ToLowerInvariant()] = $true
}

foreach ($file in $archivedFeatureLists) {
    if ($activeFeatureNames.ContainsKey($file.Name.ToLowerInvariant())) {
        Add-Error ("feature list appears in both active and archive lanes: {0}" -f $file.Name)
    }
}

# Full active-lane _Status: invariant scan — ENFORCED (hard gate).
foreach ($path in (Get-ActiveFeatureListPaths)) {
    Test-StatusInvariant $path
}

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "feature-list-lint failed with $($errors.Count) issue(s):" -ForegroundColor Red
    foreach ($e in $errors) {
        Write-Host "- $e"
    }
    exit 1
}

Write-Host "feature-list-lint passed." -ForegroundColor Green
exit 0
