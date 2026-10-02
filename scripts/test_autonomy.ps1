# PowerShell script para verificar endpoints mínimos do Duque local (não executa modelos)
# Uso: powershell.exe -ExecutionPolicy Bypass -File scripts/test_autonomy.ps1

$base = "http://127.0.0.1:5000"
Write-Host "Checando /api/estado..."
Invoke-RestMethod -Method Get -Uri "$base/api/estado" -ErrorAction Stop | ConvertTo-Json

Write-Host "Checando /api/workspace/inspect..."
try {
	Invoke-RestMethod -Method Get -Uri "$base/api/workspace/inspect" -ErrorAction Stop | ConvertTo-Json
} catch {
	Write-Host "Falha (provavelmente servidor não rodando ainda)"
}

Write-Host "Para testes de propose/approve use DUQUE_API_TOKEN e rode via curl/postman conforme necessário."