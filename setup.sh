#!/bin/bash

# 1. Actualizar el sistema e instalar dependencias básicas
echo "Actualizando el sistema..."
sudo apt-get update && sudo apt-get install -y curl python3-venv python3-pip

# 2. Instalar Ollama en el sistema operativo
if ! command -v ollama &> /dev/null
then
    echo "Instalando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama ya está instalado."
fi

# 3. Crear y activar el entorno virtual de Python
echo "Configurando el entorno virtual..."
python3 -m venv venv
source venv/bin/activate

# 4. Instalar los requerimientos de Python
echo "Instalando librerías de Python..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Descargar el modelo de Ollama
echo "Descargando modelo en Ollama..."
ollama pull llama2:7b-chat

echo "¡Todo listo! Para iniciar el bot ejecuta: source venv/bin/activate && python main.py"