param(
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "infra/docker/docker-compose.microservices.yml",
    [switch]$SkipBuild,
    [switch]$SkipBackendRestart,
    [int]$ComposeUpTimeoutSeconds = 900,
    [int]$HealthPhaseTimeoutSeconds = 300,
    [int]$ApiPhaseTimeoutSeconds = 600,
    [int]$HttpRequestTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir ("migration_validation_{0}.log" -f $ts)
$summaryFile = Join-Path $logDir ("migration_validation_{0}.summary.json" -f $ts)
$startedAt = (Get-Date).ToUniversalTime()

$script:TotalChecks = 0
$script:FailedChecks = 0
$script:WarnChecks = 0
$script:CheckResults = @()
$script:FinalResult = "FAILED"

function Write-Log {
    param(
        [string]$Level,
        [string]$Message
    )
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level.ToUpperInvariant(), $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Mark-Ok {
    param([string]$Message)
    $script:TotalChecks++
    $script:CheckResults += [pscustomobject]@{
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        level = "OK"
        message = $Message
    }
    Write-Log -Level "OK" -Message $Message
}

function Mark-Fail {
    param([string]$Message)
    $script:TotalChecks++
    $script:FailedChecks++
    $script:CheckResults += [pscustomobject]@{
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        level = "FAIL"
        message = $Message
    }
    Write-Log -Level "FAIL" -Message $Message
}

function Mark-Warn {
    param([string]$Message)
    $script:TotalChecks++
    $script:WarnChecks++
    $script:CheckResults += [pscustomobject]@{
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        level = "WARN"
        message = $Message
    }
    Write-Log -Level "WARN" -Message $Message
}

function Get-EnvValue {
    param(
        [string]$FilePath,
        [string]$Key,
        [string]$DefaultValue = ""
    )
    if (-not (Test-Path $FilePath)) {
        return $DefaultValue
    }
    $raw = Get-Content -Path $FilePath
    foreach ($line in $raw) {
        $t = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($t)) { continue }
        if ($t.StartsWith("#")) { continue }
        $eq = $t.IndexOf("=")
        if ($eq -lt 1) { continue }
        $k = $t.Substring(0, $eq).Trim()
        if ($k -ne $Key) { continue }
        $v = $t.Substring($eq + 1).Trim().Trim('"').Trim("'")
        return $v
    }
    return $DefaultValue
}

function Invoke-Cmd {
    param(
        [string]$FilePath,
        [string[]]$Args,
        [int]$TimeoutSeconds = 0
    )
    $job = Start-Job -ScriptBlock {
        param($fp, $a)
        $stdout = ""
        $stderr = ""
        $exit = 0
        try {
            $all = & $fp @a 2>&1
            $exit = $LASTEXITCODE
            if ($null -ne $all) {
                $stdout = ($all | ForEach-Object { "$_" }) -join [Environment]::NewLine
            }
        } catch {
            $exit = 1
            $stderr = $_.Exception.Message
        }
        [pscustomobject]@{
            ExitCode = $exit
            StdOut   = $stdout
            StdErr   = $stderr
            TimedOut = $false
        }
    } -ArgumentList $FilePath, $Args

    $completed = $null
    if ($TimeoutSeconds -gt 0) {
        $completed = Wait-Job -Job $job -Timeout $TimeoutSeconds
    } else {
        $completed = Wait-Job -Job $job
    }

    if ($null -eq $completed) {
        Stop-Job -Job $job -Force | Out-Null
        Remove-Job -Job $job -Force | Out-Null
        return [pscustomobject]@{
            ExitCode = 124
            StdOut   = ""
            StdErr   = ("Timeout tras {0}s ejecutando: {1} {2}" -f $TimeoutSeconds, $FilePath, ($Args -join " "))
            TimedOut = $true
        }
    }

    $res = Receive-Job -Job $job
    Remove-Job -Job $job -Force | Out-Null
    return $res
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null,
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session = $null,
        [int]$TimeoutSeconds = 30
    )
    $jsonBody = $null
    if ($null -ne $Body) {
        $jsonBody = $Body | ConvertTo-Json -Depth 20
    }

    try {
        if ($null -ne $Session) {
            if ($null -ne $jsonBody) {
                $resp = Invoke-WebRequest -Method $Method -Uri $Url -ContentType "application/json" -Body $jsonBody -WebSession $Session -UseBasicParsing -TimeoutSec $TimeoutSeconds
            } else {
                $resp = Invoke-WebRequest -Method $Method -Uri $Url -WebSession $Session -UseBasicParsing -TimeoutSec $TimeoutSeconds
            }
        } else {
            if ($null -ne $jsonBody) {
                $resp = Invoke-WebRequest -Method $Method -Uri $Url -ContentType "application/json" -Body $jsonBody -UseBasicParsing -TimeoutSec $TimeoutSeconds
            } else {
                $resp = Invoke-WebRequest -Method $Method -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
            }
        }
        $obj = $null
        if ($resp.Content) {
            try { $obj = $resp.Content | ConvertFrom-Json } catch { $obj = $resp.Content }
        }
        return [pscustomobject]@{
            Success    = $true
            StatusCode = [int]$resp.StatusCode
            Body       = $obj
            RawBody    = $resp.Content
        }
    } catch {
        $status = 0
        $raw = ""
        if ($_.Exception.Response -ne $null) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = 0 }
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                if ($stream -ne $null) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $raw = $reader.ReadToEnd()
                    $reader.Close()
                }
            } catch {
                $raw = $_.Exception.Message
            }
        } else {
            $raw = $_.Exception.Message
        }

        $obj = $null
        if ($raw) {
            try { $obj = $raw | ConvertFrom-Json } catch { $obj = $raw }
        }
        return [pscustomobject]@{
            Success    = $false
            StatusCode = $status
            Body       = $obj
            RawBody    = $raw
        }
    }
}

function Wait-Http200 {
    param(
        [string]$Name,
        [string]$Url,
        [int]$MaxAttempts = 60,
        [int]$SleepSeconds = 5,
        [datetime]$DeadlineUtc,
        [int]$TimeoutSeconds = 30
    )
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        if ($DeadlineUtc -and ((Get-Date).ToUniversalTime() -gt $DeadlineUtc)) {
            Mark-Fail ("Timeout de fase health alcanzado antes de validar {0}" -f $Name)
            return $false
        }
        $res = Invoke-Api -Method "GET" -Url $Url -TimeoutSeconds $TimeoutSeconds
        if ($res.Success -and $res.StatusCode -eq 200) {
            Mark-Ok ("{0} listo ({1})" -f $Name, $Url)
            return $true
        }
        Start-Sleep -Seconds $SleepSeconds
    }
    Mark-Fail ("{0} no respondio 200 en tiempo ({1})" -f $Name, $Url)
    return $false
}

function Wait-ApiStatus {
    param(
        [string]$Method,
        [string]$Url,
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session = $null,
        [int]$ExpectedStatus = 200,
        [int]$MaxAttempts = 12,
        [int]$SleepSeconds = 1,
        [int]$TimeoutSeconds = 30
    )
    $last = $null
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        $last = Invoke-Api -Method $Method -Url $Url -Session $Session -TimeoutSeconds $TimeoutSeconds
        if ($last.StatusCode -eq $ExpectedStatus) {
            return $last
        }
        Start-Sleep -Seconds $SleepSeconds
    }
    return $last
}

function Run-Psql {
    param([string]$Sql)
    $all = docker exec xaloc-postgres psql -U xaloc -d xaloc -t -A -c $Sql 2>&1
    $exit = $LASTEXITCODE
    $joined = ""
    if ($null -ne $all) {
        $joined = ($all | ForEach-Object { "$_" }) -join [Environment]::NewLine
    }
    return [pscustomobject]@{
        ExitCode = $exit
        StdOut   = $joined
        StdErr   = ""
        TimedOut = $false
    }
}

function Get-FirstIntFromText {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }
    $m = [regex]::Match($Text, "\b\d+\b")
    if (-not $m.Success) {
        return $null
    }
    return $m.Value
}

function New-TestResourceId {
    param([int]$MinOffset = 1000, [int]$MaxOffset = 9999)
    $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $offset = Get-Random -Minimum $MinOffset -Maximum $MaxOffset
    return [int64]($epoch + $offset)
}

Write-Log -Level "INFO" -Message ("Log file: {0}" -f $logFile)
Write-Log -Level "INFO" -Message ("Timeouts => compose_up={0}s health_phase={1}s api_phase={2}s http_request={3}s" -f $ComposeUpTimeoutSeconds, $HealthPhaseTimeoutSeconds, $ApiPhaseTimeoutSeconds, $HttpRequestTimeoutSeconds)

Push-Location $root
try {
    $envPath = Join-Path $root $EnvFile
    $composePath = Join-Path $root $ComposeFile
    if (-not (Test-Path $composePath)) {
        throw "Compose file no encontrado: $composePath"
    }
    if (-not (Test-Path $envPath)) {
        throw "Env file no encontrado: $envPath"
    }

    $buildArg = @()
    if (-not $SkipBuild) {
        $buildArg = @("--build")
    }

    Write-Log -Level "INFO" -Message "Levantando stack docker compose..."
    $composeArgs = @("compose", "--env-file", $envPath, "-f", $composePath, "up", "-d")
    if (-not $SkipBuild) {
        $composeArgs += "--build"
    }
    $composeUp = Invoke-Cmd -FilePath "docker" -Args $composeArgs -TimeoutSeconds $ComposeUpTimeoutSeconds

    if ($composeUp.ExitCode -ne 0) {
        if ($composeUp.TimedOut) {
            Mark-Fail ("docker compose up timeout tras {0}s" -f $ComposeUpTimeoutSeconds)
        } else {
            Mark-Fail ("docker compose up fallo: {0}" -f ($composeUp.StdErr.Trim()))
        }
        throw "No se pudo levantar el stack."
    } else {
        Mark-Ok "docker compose up ejecutado"
    }

    if (-not $SkipBackendRestart) {
        $pycacheGlob = Join-Path $root "dashboard/__pycache__/services*.pyc"
        Get-ChildItem -Path $pycacheGlob -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        Mark-Ok "Pycache local de dashboard/services limpiado"
        Write-Log -Level "INFO" -Message "Recreando dashboard-backend-service para cargar codigo local actualizado..."
        $restartArgs = @("compose", "--env-file", $envPath, "-f", $composePath, "up", "-d", "--no-deps", "--force-recreate", "dashboard-backend-service")
        $restartRes = Invoke-Cmd -FilePath "docker" -Args $restartArgs -TimeoutSeconds 180
        if ($restartRes.ExitCode -eq 0) {
            Mark-Ok "dashboard-backend-service recreado"
        } else {
            Mark-Warn ("No se pudo recrear dashboard-backend-service: {0}" -f ($restartRes.StdErr.Trim()))
        }
    }

    $healthDeadline = (Get-Date).ToUniversalTime().AddSeconds($HealthPhaseTimeoutSeconds)
    $allHealthy = $true
    $allHealthy = (Wait-Http200 -Name "auth-rbac-service" -Url "http://localhost:8101/health" -DeadlineUtc $healthDeadline -TimeoutSeconds $HttpRequestTimeoutSeconds) -and $allHealthy
    $allHealthy = (Wait-Http200 -Name "dashboard-backend-service" -Url "http://localhost:8788/openapi.json" -DeadlineUtc $healthDeadline -TimeoutSeconds $HttpRequestTimeoutSeconds) -and $allHealthy
    $allHealthy = (Wait-Http200 -Name "api-gateway" -Url "http://localhost:8080/health" -DeadlineUtc $healthDeadline -TimeoutSeconds $HttpRequestTimeoutSeconds) -and $allHealthy
    $allHealthy = (Wait-Http200 -Name "playwright-runner-service" -Url "http://localhost:8111/health" -DeadlineUtc $healthDeadline -TimeoutSeconds $HttpRequestTimeoutSeconds) -and $allHealthy
    $allHealthy = (Wait-Http200 -Name "signing-service" -Url "http://localhost:8112/health" -DeadlineUtc $healthDeadline -TimeoutSeconds $HttpRequestTimeoutSeconds) -and $allHealthy
    if (-not $allHealthy) {
        throw "Health checks incompletos."
    }

    $apiDeadline = (Get-Date).ToUniversalTime().AddSeconds($ApiPhaseTimeoutSeconds)
    $psqlProbe = Run-Psql -Sql "SELECT 1;"
    if ($psqlProbe.ExitCode -eq 0) {
        Mark-Ok "Conexion PostgreSQL OK (docker exec psql)"
    } else {
        Mark-Fail ("Conexion PostgreSQL fallo: {0}" -f ($psqlProbe.StdErr.Trim()))
        throw "PostgreSQL no accesible."
    }

    # Ensure pending-auth schema exists even on persistent volumes created before migration 005.
    $migrationPath = Join-Path $root "infra/postgres/init/005_pending_authorization_schema.sql"
    if (Test-Path $migrationPath) {
        $migrationSql = Get-Content -Raw $migrationPath
        $migRes = Run-Psql -Sql $migrationSql
        if ($migRes.ExitCode -eq 0) {
            Mark-Ok "Migracion pending_authorization_queue aplicada/verificada"
        } else {
            Mark-Fail ("No se pudo aplicar migracion pending_authorization_queue: {0}" -f ($migRes.StdOut.Trim()))
            throw "Fallo aplicando migration 005."
        }
    } else {
        Mark-Warn ("No existe migration file esperado: {0}" -f $migrationPath)
    }

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $adminUser = Get-EnvValue -FilePath $envPath -Key "DASHBOARD_ADMIN_USERNAME" -DefaultValue "admin"
    $adminPass = Get-EnvValue -FilePath $envPath -Key "DASHBOARD_ADMIN_PASSWORD" -DefaultValue "admin1234"

    if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de login." }
    $loginRes = Invoke-Api -Method "POST" -Url "http://localhost:8788/api/auth/login" -Body @{
        username = $adminUser
        password = $adminPass
    } -Session $session -TimeoutSeconds $HttpRequestTimeoutSeconds

    if ($loginRes.Success -and $loginRes.StatusCode -eq 200) {
        Mark-Ok ("Login dashboard OK (user={0})" -f $adminUser)
    } else {
        Mark-Fail ("Login dashboard fallo: HTTP {0} {1}" -f $loginRes.StatusCode, $loginRes.RawBody)
        throw "No se pudo autenticar en dashboard."
    }

    if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de /api/auth/me." }
    $meRes = Invoke-Api -Method "GET" -Url "http://localhost:8788/api/auth/me" -Session $session -TimeoutSeconds $HttpRequestTimeoutSeconds
    if ($meRes.Success -and $meRes.StatusCode -eq 200) {
        Mark-Ok "/api/auth/me OK"
    } else {
        Mark-Fail ("/api/auth/me fallo: HTTP {0}" -f $meRes.StatusCode)
    }

    if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de /api/pending-auth." }
    $pendingListRes = Wait-ApiStatus -Method "GET" -Url "http://localhost:8788/api/pending-auth" -Session $session -ExpectedStatus 200 -MaxAttempts 12 -SleepSeconds 1 -TimeoutSeconds $HttpRequestTimeoutSeconds
    if ($pendingListRes.Success -and $pendingListRes.StatusCode -eq 200) {
        Mark-Ok "/api/pending-auth list OK"
    } else {
        Mark-Fail ("/api/pending-auth list fallo: HTTP {0} {1}" -f $pendingListRes.StatusCode, $pendingListRes.RawBody)
    }

    if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de /api/queue/current." }
    $queueCurrentRes = Invoke-Api -Method "GET" -Url "http://localhost:8788/api/queue/current?page=1&page_size=50" -Session $session -TimeoutSeconds $HttpRequestTimeoutSeconds
    if ($queueCurrentRes.Success -and $queueCurrentRes.StatusCode -eq 200) {
        Mark-Ok "/api/queue/current OK"
    } else {
        Mark-Fail ("/api/queue/current fallo: HTTP {0}" -f $queueCurrentRes.StatusCode)
    }

    $ridApprove = New-TestResourceId -MinOffset 1000 -MaxOffset 9000
    $sqlApprove = @"
INSERT INTO pending_authorization_queue
(site_id, resource_id, payload_json, authorization_type, reason, status, created_at, updated_at)
VALUES
('madrid', $ridApprove, jsonb_build_object('idRecurso',$ridApprove,'site_id','madrid','protocol','P1','expediente','SMOKE-APPROVE-$ridApprove'), 'gesdoc', 'smoke-approve', 'pending', NOW(), NOW())
RETURNING id;
"@
    $insApprove = Run-Psql -Sql $sqlApprove
    if ($insApprove.ExitCode -ne 0) {
        Mark-Fail ("Insert pending approve fallo: {0}" -f ($insApprove.StdErr.Trim()))
        throw "No se pudo preparar prueba approve."
    }
    $pendingApproveId = Get-FirstIntFromText -Text $insApprove.StdOut
    if (-not $pendingApproveId) {
        Mark-Fail ("No se obtuvo pending_id numerico para approve. Salida psql: {0}" -f ($insApprove.StdOut.Trim()))
        throw "pending_id approve vacio."
    }
    Mark-Ok ("pending-auth preparado para approve (id={0})" -f $pendingApproveId)

    if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de approve pending-auth." }
    $approveRes = Invoke-Api -Method "POST" -Url ("http://localhost:8788/api/pending-auth/{0}/approve" -f $pendingApproveId) -Session $session -TimeoutSeconds $HttpRequestTimeoutSeconds
    if ($approveRes.Success -and $approveRes.StatusCode -eq 200) {
        Mark-Ok ("/api/pending-auth/{0}/approve OK" -f $pendingApproveId)
    } else {
        Mark-Fail ("/api/pending-auth/{0}/approve fallo: HTTP {1} {2}" -f $pendingApproveId, $approveRes.StatusCode, $approveRes.RawBody)
    }

    $checkApproveSql = "SELECT status FROM pending_authorization_queue WHERE id = $pendingApproveId;"
    $checkApprove = Run-Psql -Sql $checkApproveSql
    $approveStatus = ($checkApprove.StdOut.Trim() -split "`n" | Select-Object -Last 1).Trim().ToLowerInvariant()
    if ($checkApprove.ExitCode -eq 0 -and $approveStatus -eq "moved_to_queue") {
        Mark-Ok ("pending-auth {0} en estado moved_to_queue" -f $pendingApproveId)
    } else {
        Mark-Fail ("pending-auth {0} estado inesperado tras approve: {1}" -f $pendingApproveId, $approveStatus)
    }

    $ridReject = New-TestResourceId -MinOffset 10000 -MaxOffset 19000
    $sqlReject = @"
INSERT INTO pending_authorization_queue
(site_id, resource_id, payload_json, authorization_type, reason, status, created_at, updated_at)
VALUES
('madrid', $ridReject, jsonb_build_object('idRecurso',$ridReject,'site_id','madrid','protocol','P1','expediente','SMOKE-REJECT-$ridReject'), 'gesdoc', 'smoke-reject', 'pending', NOW(), NOW())
RETURNING id;
"@
    $insReject = Run-Psql -Sql $sqlReject
    if ($insReject.ExitCode -ne 0) {
        Mark-Fail ("Insert pending reject fallo: {0}" -f ($insReject.StdErr.Trim()))
        throw "No se pudo preparar prueba reject."
    }
    $pendingRejectId = Get-FirstIntFromText -Text $insReject.StdOut
    if (-not $pendingRejectId) {
        Mark-Fail ("No se obtuvo pending_id numerico para reject. Salida psql: {0}" -f ($insReject.StdOut.Trim()))
        throw "pending_id reject vacio."
    }
    Mark-Ok ("pending-auth preparado para reject (id={0})" -f $pendingRejectId)

    if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de reject pending-auth." }
    $rejectRes = Invoke-Api -Method "POST" -Url ("http://localhost:8788/api/pending-auth/{0}/reject" -f $pendingRejectId) -Body @{
        reason = "smoke-reject-reason"
    } -Session $session -TimeoutSeconds $HttpRequestTimeoutSeconds
    if ($rejectRes.Success -and $rejectRes.StatusCode -eq 200) {
        Mark-Ok ("/api/pending-auth/{0}/reject OK" -f $pendingRejectId)
    } else {
        Mark-Fail ("/api/pending-auth/{0}/reject fallo: HTTP {1} {2}" -f $pendingRejectId, $rejectRes.StatusCode, $rejectRes.RawBody)
    }

    $checkRejectSql = "SELECT status FROM pending_authorization_queue WHERE id = $pendingRejectId;"
    $checkReject = Run-Psql -Sql $checkRejectSql
    $rejectStatus = ($checkReject.StdOut.Trim() -split "`n" | Select-Object -Last 1).Trim().ToLowerInvariant()
    if ($checkReject.ExitCode -eq 0 -and $rejectStatus -eq "rejected") {
        Mark-Ok ("pending-auth {0} en estado rejected" -f $pendingRejectId)
    } else {
        Mark-Fail ("pending-auth {0} estado inesperado tras reject: {1}" -f $pendingRejectId, $rejectStatus)
    }

    $ridDelete = New-TestResourceId -MinOffset 20000 -MaxOffset 29000
    $jobIdDelete = "smoke-delete-$ridDelete"
    $dedupDelete = "madrid:$ridDelete:P1:$jobIdDelete"
    $sqlDelete = @"
INSERT INTO jobs
(job_id, organism_id, dedup_key, status, priority, payload_json, queued_at, created_at, updated_at)
VALUES
('$jobIdDelete', NULL, '$dedupDelete', 'queued', 100, jsonb_build_object('idRecurso',$ridDelete,'site_id','madrid','protocol','P1','expediente','SMOKE-DELETE-$ridDelete'), NOW(), NOW(), NOW());
"@
    $insDelete = Run-Psql -Sql $sqlDelete
    if ($insDelete.ExitCode -ne 0) {
        Mark-Fail ("Insert queue item para DELETE fallo: {0}" -f ($insDelete.StdErr.Trim()))
    } else {
        Mark-Ok ("queue item preparado para DELETE (resource_id={0})" -f $ridDelete)
        if ((Get-Date).ToUniversalTime() -gt $apiDeadline) { throw "Timeout de fase API antes de DELETE queue item." }
        $deleteRes = Invoke-Api -Method "DELETE" -Url ("http://localhost:8788/api/queue/items/madrid/{0}" -f $ridDelete) -Session $session -TimeoutSeconds $HttpRequestTimeoutSeconds
        if ($deleteRes.Success -and $deleteRes.StatusCode -eq 200) {
            if ($deleteRes.Body.removed -eq $true) {
                Mark-Ok ("/api/queue/items/madrid/{0} DELETE OK" -f $ridDelete)
            } else {
                Mark-Fail ("/api/queue/items/madrid/{0} DELETE devolvio removed=false ({1})" -f $ridDelete, ($deleteRes.RawBody))
            }
        } elseif ($deleteRes.StatusCode -eq 500 -and ($deleteRes.RawBody -like "*faltan XVIA_EMAIL/XVIA_PASSWORD*")) {
            Mark-Warn ("/api/queue/items/madrid/{0} elimino cola pero fallo deseleccion XVIA por credenciales no configuradas" -f $ridDelete)
        } else {
            Mark-Fail ("/api/queue/items/madrid/{0} DELETE fallo: HTTP {1} {2}" -f $ridDelete, $deleteRes.StatusCode, $deleteRes.RawBody)
        }
    }

    $schemaCheck = Run-Psql -Sql "SELECT to_regclass('public.pending_authorization_queue');"
    $schemaValue = ($schemaCheck.StdOut.Trim() -split "`n" | Select-Object -Last 1).Trim()
    if ($schemaCheck.ExitCode -eq 0 -and $schemaValue -eq "pending_authorization_queue") {
        Mark-Ok "Tabla pending_authorization_queue existe en PG"
    } else {
        Mark-Fail "Tabla pending_authorization_queue no existe en PG"
    }
}
catch {
    Write-Log -Level "ERROR" -Message $_.Exception.Message
}
finally {
    $finishedAt = (Get-Date).ToUniversalTime()
    $summary = "Checks={0} OK={1} WARN={2} FAIL={3}" -f $script:TotalChecks, ($script:TotalChecks - $script:FailedChecks - $script:WarnChecks), $script:WarnChecks, $script:FailedChecks
    $script:FinalResult = if ($script:FailedChecks -gt 0) { "FAILED" } else { "OK" }
    $summaryObj = [pscustomobject]@{
        result = $script:FinalResult
        started_at_utc = $startedAt.ToString("o")
        finished_at_utc = $finishedAt.ToString("o")
        duration_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
        counts = [pscustomobject]@{
            checks = $script:TotalChecks
            ok = ($script:TotalChecks - $script:FailedChecks - $script:WarnChecks)
            warn = $script:WarnChecks
            fail = $script:FailedChecks
        }
        files = [pscustomobject]@{
            log = $logFile
            summary = $summaryFile
        }
        checks = $script:CheckResults
    }
    $summaryObj | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryFile -Encoding UTF8
    Write-Log -Level "INFO" -Message ("Summary JSON: {0}" -f $summaryFile)
    if ($script:FailedChecks -gt 0) {
        Write-Log -Level "RESULT" -Message ("VALIDATION FAILED | {0}" -f $summary)
        Pop-Location
        exit 2
    } else {
        Write-Log -Level "RESULT" -Message ("VALIDATION OK | {0}" -f $summary)
        Pop-Location
        exit 0
    }
}
