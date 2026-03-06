param(
    [string]$ContainerName = "xaloc-playwright-runner",
    [int]$SinceMinutes = 20,
    [string]$OutputBaseDir = "tmp/redsara-log-captures",
    [switch]$Follow
)

$ErrorActionPreference = "Stop"

function New-OutputDir {
    param([string]$BaseDir)
    $ts = Get-Date -Format "yyyyMMdd-HHmmss"
    $dir = Join-Path $BaseDir "redsara-$ts"
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    return $dir
}

function Write-TextFile {
    param(
        [string]$Path,
        [string]$Content
    )
    $folder = Split-Path -Parent $Path
    if ($folder) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
    }
    Set-Content -Path $Path -Value $Content -Encoding UTF8
}

function Docker-ExecSafe {
    param(
        [string]$Container,
        [string]$Command
    )
    try {
        return & docker exec $Container sh -lc $Command 2>&1 | Out-String
    } catch {
        return "[ERROR] docker exec failed for command: $Command`n$($_.Exception.Message)"
    }
}

function Docker-LogsSafe {
    param(
        [string]$Container,
        [int]$Minutes
    )
    # Evita excepciones por stderr no crítico en PowerShell.
    $tmpErr = [System.IO.Path]::GetTempFileName()
    try {
        $output = & cmd /c "docker logs --since ${Minutes}m $Container 2> `"$tmpErr`""
        $stderr = ""
        if (Test-Path $tmpErr) {
            $stderr = Get-Content -Raw $tmpErr -ErrorAction SilentlyContinue
        }
        $txt = (($output | Out-String) + $stderr).Trim()
        if (-not $txt) {
            return "[INFO] docker logs returned no lines for last ${Minutes}m."
        }
        return $txt
    } catch {
        return "[ERROR] docker logs failed: $($_.Exception.Message)"
    } finally {
        Remove-Item -Path $tmpErr -Force -ErrorAction SilentlyContinue
    }
}

function Get-ContainerStatus {
    param([string]$Container)
    try {
        $status = & docker ps --filter "name=$Container" --format "{{.Status}}" 2>&1
        return ($status | Out-String).Trim()
    } catch {
        return ""
    }
}

if ($Follow) {
    Write-Host "[redsara-logs] Following live logs for container '$ContainerName'..."
    & docker logs -f $ContainerName
    exit $LASTEXITCODE
}

$status = Get-ContainerStatus -Container $ContainerName
if (-not $status) {
    throw "Container '$ContainerName' is not running or not found in docker ps."
}

$outDir = New-OutputDir -BaseDir $OutputBaseDir
Write-Host "[redsara-logs] Capturing logs to: $outDir"
Write-Host "[redsara-logs] Container: $ContainerName ($status)"

$meta = @(
    "timestamp=$(Get-Date -Format o)"
    "container=$ContainerName"
    "status=$status"
    "since_minutes=$SinceMinutes"
) -join "`n"
Write-TextFile -Path (Join-Path $outDir "meta.txt") -Content $meta

# 1) Container logs (last N minutes)
$dockerLogs = Docker-LogsSafe -Container $ContainerName -Minutes $SinceMinutes
Write-TextFile -Path (Join-Path $outDir "docker-logs.txt") -Content $dockerLogs

# 2) Relevant /tmp files and runtime state inside container
$commands = @{
    "tmp-xaloc-afirma-uri.log.txt"     = "test -f /tmp/xaloc_afirma_uri.log && cat /tmp/xaloc_afirma_uri.log || echo '[missing] /tmp/xaloc_afirma_uri.log'"
    "tmp-xaloc-afirma-uri.latest.txt"  = "test -f /tmp/xaloc_afirma_uri.latest && cat /tmp/xaloc_afirma_uri.latest || echo '[missing] /tmp/xaloc_afirma_uri.latest'"
    "tmp-xaloc-afirma-proxy.log.txt"   = "test -f /tmp/xaloc_afirma_proxy.log && cat /tmp/xaloc_afirma_proxy.log || echo '[missing] /tmp/xaloc_afirma_proxy.log'"
    "tmp-xaloc-afirma-forensic.log.txt" = "test -f /tmp/xaloc_afirma_forensic.jsonl && cat /tmp/xaloc_afirma_forensic.jsonl || echo '[missing] /tmp/xaloc_afirma_forensic.jsonl'"
    "tmp-xaloc-afirma-forensic-ls.txt"  = "if [ -d /tmp/xaloc_afirma_forensic_payloads ]; then ls -la /tmp/xaloc_afirma_forensic_payloads | sed -n '1,400p'; else echo '[missing] /tmp/xaloc_afirma_forensic_payloads'; fi"
    "tmp-xaloc-afirma-forensic-last-out-sign.txt" = 'if [ -d /tmp/xaloc_afirma_forensic_payloads ]; then f=$(ls -1t /tmp/xaloc_afirma_forensic_payloads/*-out-*-sign-* 2>/dev/null | head -n 1); echo "FILE=$f"; if [ -n "$f" ]; then wc -c "$f"; cat "$f"; else echo "[missing] no out sign payload file"; fi; else echo "[missing] /tmp/xaloc_afirma_forensic_payloads"; fi'
    "tmp-xaloc-afirma-proxy.ready.txt" = "test -f /tmp/xaloc_afirma_proxy.ready && cat /tmp/xaloc_afirma_proxy.ready || echo '[missing] /tmp/xaloc_afirma_proxy.ready'"
    "tmp-xaloc-afirma-proxy.pid.txt"   = "test -f /tmp/xaloc_afirma_proxy.pid && cat /tmp/xaloc_afirma_proxy.pid || echo '[missing] /tmp/xaloc_afirma_proxy.pid'"
    "tmp-ls.txt"                       = "ls -la /tmp | sed -n '1,240p'"
    "ps-grep-afirma.txt"               = "ps -ef | grep -E 'autofirma|afirma-handler|python3 .*autofirma_proxy' | grep -v grep || true"
    "xdg-mime-afirma.txt"              = "xdg-mime query default x-scheme-handler/afirma 2>/dev/null || true; xdg-mime query default x-scheme-handler/xalocafirma 2>/dev/null || true"
    "afirma-handler.sh.txt"            = "test -f /usr/local/bin/afirma-handler.sh && cat /usr/local/bin/afirma-handler.sh || echo '[missing] /usr/local/bin/afirma-handler.sh'"
    "afirma-policy.txt"                = "if [ -f /etc/chromium/policies/managed/xaloc-afirma-policy.json ]; then echo '==== /etc/chromium/policies/managed/xaloc-afirma-policy.json ===='; cat /etc/chromium/policies/managed/xaloc-afirma-policy.json; fi; if [ -f /etc/opt/chrome/policies/managed/xaloc-afirma-policy.json ]; then echo '==== /etc/opt/chrome/policies/managed/xaloc-afirma-policy.json ===='; cat /etc/opt/chrome/policies/managed/xaloc-afirma-policy.json; fi; if [ -f /etc/opt/chrome_for_testing/policies/managed/xaloc-afirma-policy.json ]; then echo '==== /etc/opt/chrome_for_testing/policies/managed/xaloc-afirma-policy.json ===='; cat /etc/opt/chrome_for_testing/policies/managed/xaloc-afirma-policy.json; fi; if [ -f /etc/opt/edge/policies/managed/xaloc-afirma-policy.json ]; then echo '==== /etc/opt/edge/policies/managed/xaloc-afirma-policy.json ===='; cat /etc/opt/edge/policies/managed/xaloc-afirma-policy.json; fi"
}

foreach ($entry in $commands.GetEnumerator()) {
    $filePath = Join-Path $outDir $entry.Key
    $content = Docker-ExecSafe -Container $ContainerName -Command $entry.Value
    Write-TextFile -Path $filePath -Content $content
}

# 3) Quick grep summary
$summary = @()
$summary += "=== quick grep in docker-logs ==="
$summary += (Select-String -Path (Join-Path $outDir "docker-logs.txt") -Pattern "afirma-handler|autofirma-proxy|AutoLaunchProtocolsFromOrigins|EADDRINUSE|Connection refused|Operation received|Proxy ready|idsession|sign error" -CaseSensitive:$false | ForEach-Object { $_.Line } | Select-Object -First 200)
$summaryText = ($summary -join "`n")
Write-TextFile -Path (Join-Path $outDir "summary-grep.txt") -Content $summaryText

Write-Host "[redsara-logs] Done."
Write-Host "[redsara-logs] Files written under: $outDir"
Write-Host "[redsara-logs] Suggested next step: run Redsara attempt, then rerun this script and share summary-grep.txt + tmp-xaloc-afirma-proxy.log.txt"
