# Script de redémarrage du backend PadelVar
# Utilisation: .\restart_backend.ps1

Write-Host "🔄 Redémarrage du backend PadelVar..." -ForegroundColor Cyan

# Arrêter tous les processus Python liés à app.py
$processes = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
        $cmdLine -like "*app.py*"
    } catch {
        $false
    }
}

if ($processes) {
    Write-Host "⏹️  Arrêt des processus backend existants..." -ForegroundColor Yellow
    $processes | ForEach-Object {
        Write-Host "   Arrêt processus PID: $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Write-Host "✅ Processus arrêtés" -ForegroundColor Green
} else {
    Write-Host "ℹ️  Aucun processus backend actif" -ForegroundColor Gray
}

# Démarrer le nouveau processus
Write-Host ""
Write-Host "🚀 Démarrage du backend..." -ForegroundColor Cyan
Set-Location "C:\Users\PC\Downloads\pladelvar_integrated_v94\v94_app\V9\padelvar-backend-main"

# Lancer en arrière-plan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python app.py" -WindowStyle Normal

Start-Sleep -Seconds 3
Write-Host ""
Write-Host "✅ Backend démarré!" -ForegroundColor Green
Write-Host "📍 URL: http://localhost:5000" -ForegroundColor White
Write-Host ""
Write-Host "Vérification du démarrage..." -ForegroundColor Gray
Start-Sleep -Seconds 2

# Vérifier que le processus est actif
$newProcess = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
        $cmdLine -like "*app.py*"
    } catch {
        $false
    }
} | Select-Object -First 1

if ($newProcess) {
    Write-Host "✅ Processus actif - PID: $($newProcess.Id)" -ForegroundColor Green
} else {
    Write-Host "⚠️  Impossible de vérifier le processus" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "ℹ️  Consultez la fenêtre PowerShell ouverte pour les logs" -ForegroundColor Cyan
