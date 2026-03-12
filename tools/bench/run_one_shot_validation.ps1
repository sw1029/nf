param(
    [string]$BaseUrl = "http://127.0.0.1:8085",
    [string]$DatasetInputDir = "test_files",
    [string]$DatasetOutputDir = "verify/datasets",
    [string]$BenchOutputDir = "verify/benchmarks",
    [int]$Seed = 20260307,
    [int]$InjectSampleSize = 200,
    [ValidateSet("basic", "max")]
    [string]$DiversityProfile = "max",
    [switch]$SkipLiveBench,
    [switch]$SkipFailureProbe
)

$ErrorActionPreference = "Stop"

$judgeEnvKeys = @(
    "NF_ENABLE_TEST_JUDGE_LOCAL_NLI",
    "NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID",
    "NF_TEST_JUDGE_MIN_CONFIDENCE",
    "NF_TEST_JUDGE_TIMEOUT_MS"
)
$savedJudgeEnv = @{}

function Write-Step {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] $Message"
}

function Invoke-PythonJson {
    param([string[]]$Arguments)
    $raw = & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python command failed: python $($Arguments -join ' ')"
    }
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        return $raw | ConvertFrom-Json
    }
    return $null
}

function Invoke-PythonJsonAllowExpectedFailure {
    param([string[]]$Arguments)
    $raw = & python @Arguments
    if ($LASTEXITCODE -notin @(0, 1, 2)) {
        throw "python command failed with unexpected exit code ${LASTEXITCODE}: python $($Arguments -join ' ')"
    }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "python command returned empty stdout: python $($Arguments -join ' ')"
    }
    try {
        return $raw | ConvertFrom-Json
    } catch {
        throw "python command returned non-JSON stdout: python $($Arguments -join ' ')"
    }
}

function Set-TestJudgeEnv {
    foreach ($key in $judgeEnvKeys) {
        $savedJudgeEnv[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    }
    $env:NF_ENABLE_TEST_JUDGE_LOCAL_NLI = "true"
    $env:NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID = "nli-lite-v1"
    $env:NF_TEST_JUDGE_MIN_CONFIDENCE = "0.80"
    $env:NF_TEST_JUDGE_TIMEOUT_MS = "3000"
}

function Restore-TestJudgeEnv {
    foreach ($key in $judgeEnvKeys) {
        $value = $savedJudgeEnv[$key]
        if ($null -eq $value) {
            Remove-Item "Env:$key" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Test-StackHealth {
    param([string]$Url)
    try {
        $res = Invoke-WebRequest -UseBasicParsing "$Url/health" -TimeoutSec 5
        return ($res.Content | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "required JSON artifact missing: $Path"
    }
    $raw = Get-Content -Raw -Encoding utf8 $Path
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "JSON artifact is empty: $Path"
    }
    try {
        return $raw | ConvertFrom-Json
    } catch {
        throw "failed to parse JSON artifact: $Path"
    }
}

function Assert-ObjectPath {
    param(
        [Parameter(Mandatory = $true)] [object]$Object,
        [Parameter(Mandatory = $true)] [string]$Path
    )
    $current = $Object
    foreach ($segment in ($Path -split '\.')) {
        if ($null -eq $current) {
            throw "required path missing: $Path"
        }
        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            throw "required path missing: $Path"
        }
        $current = $property.Value
    }
    if ($null -eq $current) {
        throw "required path resolved to null: $Path"
    }
    return $current
}

function Resolve-AnyObjectPath {
    param(
        [Parameter(Mandatory = $true)] [object]$Object,
        [Parameter(Mandatory = $true)] [string[]]$Paths
    )
    foreach ($candidate in $Paths) {
        try {
            $value = Assert-ObjectPath -Object $Object -Path $candidate
            return [pscustomobject]@{
                Path = $candidate
                Value = $value
            }
        } catch {
            continue
        }
    }
    throw "required path missing: $($Paths -join ' | ')"
}

function Convert-ToBooleanStrict {
    param(
        [Parameter(Mandatory = $true)] [object]$Value,
        [Parameter(Mandatory = $true)] [string]$Path
    )
    if ($Value -is [bool]) {
        return [bool]$Value
    }
    if ($Value -is [string]) {
        $normalized = $Value.Trim().ToLowerInvariant()
        if ($normalized -eq "true") {
            return $true
        }
        if ($normalized -eq "false") {
            return $false
        }
    }
    throw "required boolean path invalid: ${Path}"
}

function Resolve-LiveBenchGuardState {
    param(
        [Parameter(Mandatory = $true)] [object]$Artifact
    )
    $guardState = Resolve-AnyObjectPath -Object $Artifact -Paths @(
        "guards",
        "semantic.guards",
        "runs.throughput.guards",
        "runs.throughput.semantic.guards"
    )
    $guardNames = @(
        "index_jobs_succeeded",
        "ingest_failures_zero",
        "consistency_failures_zero",
        "retrieve_vec_failures_zero"
    )
    $resolved = [ordered]@{}
    foreach ($guardName in $guardNames) {
        $guardValue = Assert-ObjectPath -Object $guardState.Value -Path $guardName
        $resolved[$guardName] = Convert-ToBooleanStrict -Value $guardValue -Path "$($guardState.Path).$guardName"
    }
    return [pscustomobject]@{
        Path = $guardState.Path
        Guards = [pscustomobject]$resolved
    }
}

$artifactPaths = [ordered]@{}
$liveBenchRuntimePassed = $false
$liveBenchBlockedReason = "live bench runtime smoke did not run"

# Root cause note:
# PowerShell 5.1's Set-Content -Encoding utf8 writes a UTF-8 BOM.
# The loader is now BOM-safe, but this script still avoids touching TOML and
# uses process-scoped env vars only for the dataset build step.

Write-Step "Step 1/6 - dataset rebuild (env override, no TOML write)"
Set-TestJudgeEnv
try {
    $datasetResult = Invoke-PythonJson @(
        "tools/bench/build_novel_dataset.py",
        "--input-dir", $DatasetInputDir,
        "--output-dir", $DatasetOutputDir,
        "--inject-sample-size", "$InjectSampleSize",
        "--seed", "$Seed",
        "--diversity-profile", $DiversityProfile
    )
} finally {
    Restore-TestJudgeEnv
}
$datasetSummaryPath = [string](Assert-ObjectPath -Object $datasetResult -Path "summary_path")
$artifactPaths["dataset_manifest"] = $datasetSummaryPath
$datasetSummary = Read-JsonFile -Path $datasetSummaryPath
$datasetGenerationVersion = [string](Assert-ObjectPath -Object $datasetSummary -Path "dataset_generation_version")
$datasetRegistryVersion = [string](Assert-ObjectPath -Object $datasetSummary -Path "source_policy_registry_version")
$localProfileCount = [int](Assert-ObjectPath -Object $datasetSummary -Path "datasets.DS-GROWTH-200.local_profile_only_record_count")
$null = Assert-ObjectPath -Object $datasetSummary -Path "datasets.DS-GROWTH-200.consistency_corroboration_policy_counts"
Write-Step "dataset rebuild output: $datasetSummaryPath"
Write-Step "dataset manifest version: $datasetGenerationVersion / registry: $datasetRegistryVersion"
Write-Step "dataset corroboration policy counts: local_profile_only=$localProfileCount"

Write-Step "Step 2/6 - governance check"
$governance = Invoke-PythonJson @(
    "tools/quality/check_source_filename_governance.py",
    "--repo-root", ".",
    "--source-dir", $DatasetInputDir
)
if (-not $governance.ok) {
    throw "filename governance check failed"
}
Write-Step "governance check passed"

Write-Step "Step 3/6 - regression tests"
& pytest -q `
    tests/test_tools_quality_source_filename_governance.py `
    tests/test_nf_shared_protocol.py `
    tests/test_tools_bench_http_client.py `
    tests/test_tools_bench_build_novel_dataset.py `
    tests/test_tools_bench_run_pipeline_bench.py `
    tests/test_tools_bench_run_one_shot_validation.py `
    tests/test_tools_bench_judge_audit.py `
    tests/test_tools_bench_shared_utils.py `
    tests/test_nf_consistency_filters.py `
    tests/test_tools_bench_metrics_summary.py `
    tests/test_tools_bench_strict_gate.py `
    tests/test_nf_consistency_engine.py `
    tests/test_nf_consistency_slot_equivalence.py `
    tests/consistency/test_engine_quality_core.py `
    tests/consistency/test_engine_quality_graph.py `
    tests/consistency/test_engine_quality_layer3.py
if ($LASTEXITCODE -ne 0) {
    throw "pytest regression suite failed"
}
Write-Step "regression tests passed"

$health = Test-StackHealth -Url $BaseUrl
if ($SkipLiveBench) {
    Write-Step "Step 4/6 - live bench skipped by flag"
    $liveBenchBlockedReason = "live bench skipped by flag"
} elseif ($null -eq $health) {
    Write-Step "Step 4/6 - live bench skipped (stack not healthy at $BaseUrl)"
    $liveBenchBlockedReason = "front-door unreachable"
} else {
    Write-Step "Step 4/6 - live bench throughput validation"
    $benchResult = Invoke-PythonJson @(
        "tools/bench/run_pipeline_bench.py",
        "--base-url", $BaseUrl,
        "--dataset", "verify/datasets/DS-INJECT-C.jsonl",
        "--project-name", "bench-one-shot-check",
        "--bench-label", "validation:one-shot",
        "--limit-docs", "1",
        "--consistency-samples", "1",
        "--output-dir", $BenchOutputDir,
        "--profile", "throughput",
        "--seed", "$Seed"
    )
    $benchOutputPath = [string](Assert-ObjectPath -Object $benchResult -Path "output")
    $artifactPaths["live_bench"] = $benchOutputPath
    $benchArtifact = Read-JsonFile -Path $benchOutputPath
    $null = Assert-ObjectPath -Object $benchArtifact -Path "frontdoor_probe"
    $manifestEntryPath = Resolve-AnyObjectPath -Object $benchArtifact -Paths @(
        "semantic.dataset_profile.dataset_manifest_entry",
        "runs.throughput.semantic.dataset_profile.dataset_manifest_entry"
    )
    $guardState = Resolve-LiveBenchGuardState -Artifact $benchArtifact
    $failedGuards = @(
        $guardState.Guards.PSObject.Properties |
            Where-Object { -not [bool]$_.Value } |
            ForEach-Object { $_.Name }
    )
    Write-Step "live bench output: $benchOutputPath"
    Write-Step "live bench manifest entry path: $($manifestEntryPath.Path)"
    Write-Step "live bench schema/provenance smoke passed"
    if ($failedGuards.Count -gt 0) {
        $failedGuardText = $failedGuards -join ", "
        throw "live bench runtime smoke failed (stack reachable but bench failed): guard path $($guardState.Path); failed guards: $failedGuardText"
    }
    $liveBenchRuntimePassed = $true
    $liveBenchBlockedReason = ""
    Write-Step "live bench runtime smoke passed"
}

if ($SkipFailureProbe) {
    Write-Step "Step 5/6 - failure probe skipped by flag"
} else {
    Write-Step "Step 5/6 - failure artifact validation"
    $failureResult = Invoke-PythonJsonAllowExpectedFailure @(
        "tools/bench/run_pipeline_bench.py",
        "--base-url", "http://127.0.0.1:9",
        "--dataset", "verify/datasets/DS-GROWTH-50.jsonl",
        "--project-name", "bench-failure-check",
        "--bench-label", "validation:transport-failure",
        "--limit-docs", "1",
        "--consistency-samples", "1",
        "--output-dir", $BenchOutputDir,
        "--profile", "throughput",
        "--seed", "$Seed"
    )
    if ($failureResult.ok) {
        throw "failure probe unexpectedly succeeded"
    }
    $failureOutputPath = [string](Assert-ObjectPath -Object $failureResult -Path "output")
    $artifactPaths["failure_probe"] = $failureOutputPath
    $failureArtifact = Read-JsonFile -Path $failureOutputPath
    $null = Assert-ObjectPath -Object $failureArtifact -Path "attempt_stage"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "attempt_index"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "request_method"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "request_path"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "error_class"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "retry_count"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "retryable"
    $null = Assert-ObjectPath -Object $failureArtifact -Path "backoff_total_sec"
    Write-Step "failure artifact output: $failureOutputPath"
    Write-Step "expected failure validated"
}

if (-not $liveBenchRuntimePassed) {
    Write-Step "Step 6/6 - delegated long runs blocked"
} else {
    Write-Step "Step 6/6 - delegated long runs ready"
}
$judgeCmd = '$env:NF_ENABLE_TEST_JUDGE_LOCAL_NLI="true"; $env:NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID="nli-lite-v1"; $env:NF_TEST_JUDGE_MIN_CONFIDENCE="0.80"; $env:NF_TEST_JUDGE_TIMEOUT_MS="3000"; python tools/bench/build_novel_dataset.py --input-dir test_files --output-dir verify/datasets --inject-sample-size 200 --seed 20260307 --diversity-profile max'
$ds800Cmd = "python tools/bench/run_pipeline_bench.py --base-url $BaseUrl --dataset verify/datasets/DS-GROWTH-800.jsonl --project-name bench-ds800-operational --bench-label operational-main:DS-800 --limit-docs 800 --consistency-samples 100 --output-dir $BenchOutputDir --profile throughput --seed $Seed"
$localProfileShadowCmd = "python tools/bench/run_pipeline_bench.py --base-url $BaseUrl --dataset verify/datasets/DS-GROWTH-200.jsonl --project-name bench-local-profile-shadow --bench-label operational-shadow:local-profile-only --limit-docs 200 --consistency-samples 30 --output-dir $BenchOutputDir --profile throughput --seed $Seed --only-local-profile-only --include-local-profile-only"
$layer3ControlCmd = "python tools/bench/run_pipeline_bench.py --base-url $BaseUrl --dataset verify/datasets/DS-CONTROL-D.jsonl --project-name bench-strict-layer3-control --bench-label operational-strict:control --limit-docs 200 --consistency-samples 100 --output-dir $BenchOutputDir --profile throughput --consistency-level strict --seed $Seed"
$layer3InjectCmd = "python tools/bench/run_pipeline_bench.py --base-url $BaseUrl --dataset verify/datasets/DS-INJECT-C.jsonl --project-name bench-strict-layer3-inject --bench-label operational-strict:inject --limit-docs 200 --consistency-samples 100 --output-dir $BenchOutputDir --profile throughput --consistency-level strict --seed $Seed"

Write-Host ""
Write-Host "Artifacts:"
foreach ($item in $artifactPaths.GetEnumerator()) {
    Write-Host "$($item.Key): $($item.Value)"
}

Write-Host ""
if (-not $liveBenchRuntimePassed) {
    Write-Host "Pending after validation:one-shot guard pass:"
} else {
    Write-Host "Delegated commands:"
}
Write-Host $judgeCmd
Write-Host $ds800Cmd
Write-Host $localProfileShadowCmd
Write-Host $layer3ControlCmd
Write-Host $layer3InjectCmd

Write-Host ""
if (-not $liveBenchRuntimePassed) {
    Write-Host "One-shot validation completed without delegated readiness."
    throw "one-shot delegated readiness blocked: $liveBenchBlockedReason"
} else {
    Write-Host "One-shot validation completed."
}
