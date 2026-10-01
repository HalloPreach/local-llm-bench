param([string]$LogPath)
$ErrorActionPreference = 'Stop'
$syncRoot = $PSScriptRoot
$pythonPath = (Get-Command python -ErrorAction Stop).Source
if (-not $LogPath) {
    $workspaceLog = Join-Path $syncRoot 'logs\ninfer.stderr.log'
    if (Test-Path -LiteralPath $workspaceLog) {
        $LogPath = $workspaceLog
    } else {
        $LogPath = Get-ChildItem -Path "$env:LOCALAPPDATA\ninfer-windows\*\server.stderr.log" -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $LogPath -or -not (Test-Path -LiteralPath $LogPath)) {
    throw 'Journal nInfer introuvable; fournissez -LogPath.'
}
$syncScript = Join-Path $syncRoot 'sync_metrics.py'
$syncArgs = '"' + $syncScript + '" --log "' + $LogPath + '" --include-bridge'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $syncArgs -WorkingDirectory $syncRoot
$scheduledUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $scheduledUser -LogonType Interactive -RunLevel Limited
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) -RepetitionInterval (New-TimeSpan -Minutes 10)
$login = New-ScheduledTaskTrigger -AtLogOn -User $scheduledUser
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'LocalLLMBenchMetricsSync' -Action $action -Trigger @($periodic, $login) -Principal $principal -Settings $settings -Description 'Publie les métriques nInfer publiques sans prompts ni réponses toutes les 10 minutes.' -Force | Out-Null
Start-ScheduledTask -TaskName 'LocalLLMBenchMetricsSync'
Write-Output "Synchronisation installée: toutes les 10 minutes et à l'ouverture de session."
