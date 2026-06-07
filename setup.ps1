# setup.ps1


# 1. Ajustar la política de ejecución temporalmente para este script y sesión
Write-Host "Configurando permisos de ejecución en PowerShell..." -ForegroundColor Cyan
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force

# 2. Verificar si Ollama está instalado/corriendo
Write-Host "Verificando Ollama..." -ForegroundColor Cyan
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama detectado en el sistema." -ForegroundColor Green
} else {
    Write-Host "¡Ollama no se detectó en la consola! Asegúrate de haberlo descargado de https://ollama.com e instalado primero." -ForegroundColor Yellow
}

# 3. Crear el entorno virtual de Python si no existe
if (-not (Test-Path ".\venv")) {
    Write-Host "Creando el entorno virtual de Python (venv)..." -ForegroundColor Cyan
    python -m venv venv
} else {
    Write-Host "El entorno virtual (venv) ya existe." -ForegroundColor Green
}

# 4. Activar el entorno virtual e instalar requerimientos
Write-Host "Activando entorno virtual e instalando librerías..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

# Actualizar pip e instalar los requerimientos de tu archivo txt
python -m pip install --upgrade pip
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
} else {
    Write-Host "No se encontró el archivo requirements.txt en este directorio." -ForegroundColor Yellow
}

# 5. Descargar el modelo de Ollama
Write-Host "Descargando modelo llama2:7b-chat en Ollama..." -ForegroundColor Cyan
ollama pull llama2:7b-chat

Write-Host ""
Write-Host "¡Todo listo en Windows!" -ForegroundColor Green
Write-Host "Para iniciar el bot en el futuro, ejecuta estos dos comandos:" -ForegroundColor White
Write-Host "1) .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "2) python main.py" -ForegroundColor Yellow