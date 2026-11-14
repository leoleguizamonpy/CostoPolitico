# CostoPolitico en Windows: todo de una.
#   Doble clic en correr.bat   (o en PowerShell:  .\correr.ps1)
#   Carga completa 2023-2026:  .\correr.bat -Completo
# Requisito: Python 3.10 o más nuevo (python.org, marcando "Add python.exe to PATH").

param([switch]$Completo)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"              # tildes y el símbolo ₲ sin errores en la consola
$env:PYTHONIOENCODING = "utf-8"

function Paso($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

# 1. Buscar Python
Paso "Buscando Python"
$pyExe = $null; $pyArgs = @()
foreach ($c in @(@("py", "-3"), @("python"), @("python3"))) {
    $exe = $c[0]
    $extra = @(); if ($c.Count -gt 1) { $extra = $c[1..($c.Count - 1)] }
    try {
        $v = & $exe @extra -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
        if ($v -eq "True") { $pyExe = $exe; $pyArgs = $extra; break }
    } catch {}
}
if (-not $pyExe) {
    Write-Host "No encontré Python 3.10 o más nuevo." -ForegroundColor Red
    Write-Host "Instalalo desde https://www.python.org/downloads/ (marcá 'Add python.exe to PATH') y volvé a correr este script."
    Read-Host "Enter para salir"; exit 1
}
Write-Host "Usando: $pyExe $($pyArgs -join ' ')"

# 2. Entorno virtual y dependencias
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Paso "Creando el entorno de Python (.venv)"
    & $pyExe @pyArgs -m venv .venv
}
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Paso "Instalando dependencias"
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias" }

# 3. Datos (primero las cámaras: de ahí salen las personas; después sueldos y viajes)
$script:fallas = @()
function Correr($argumentos) {
    # Si una fuente falla se avisa y se sigue: la web se genera igual con lo que se haya bajado.
    & $vpy -m costopolitico @argumentos
    if ($LASTEXITCODE -ne 0) {
        $script:fallas += ($argumentos -join " ")
        Write-Host "AVISO: falló 'costopolitico $($argumentos -join ' ')'. Sigo con lo demás." -ForegroundColor Yellow
    }
}
if ($Completo) {
    Paso "Carga completa 2023-2026 (unos 1,5 GB de nómina; puede tardar horas)"
    Correr @("actualizar", "--desde", "2023", "--sueldos-desde", "2023-07")
} else {
    Paso "Diputados: nómina, partidos y viáticos"
    Correr @("diputados", "--desde", "2025")
    Paso "Senado: nómina, partidos y viajes"
    Correr @("senado", "--desde", "2025")
    Paso "Sueldos (nómina SFP) desde enero de 2026"
    Correr @("sueldos", "--desde", "2026-01")
    Paso "Generando la web"
    Correr @("exportar")
}

if ($script:fallas.Count -gt 0) {
    Write-Host "`nTerminó con fallas en: $($script:fallas -join '; ')" -ForegroundColor Yellow
    Write-Host "Copiá los mensajes de error de arriba para corregirlos. La web se abre igual con lo que se cargó."
}

# 4. Controles automáticos de consistencia
Paso "Controles automáticos (data\verificacion\)"
Correr @("controles")

# 5. Pendientes de revisión
Paso "Pendientes de revisión (data\revision.csv)"
Correr @("pendientes", "--csv", "data\revision.csv")

# 6. Abrir la web
Paso "Abriendo http://localhost:8000  (cerrá esta ventana para apagar el servidor)"
Start-Process "http://localhost:8000"
& $vpy -m http.server 8000 --directory web
