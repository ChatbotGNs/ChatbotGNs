#!/bin/bash

# 1. Actualizar el sistema y preparar repositorios
echo "Actualizando el sistema..."
sudo apt-get update
sudo apt-get install -y software-properties-common curl

# Añadir el repositorio oficial para versiones específicas de Python
echo "Añadiendo repositorio de Python..."
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update

# Instalar explícitamente Python 3.11 y su módulo venv
echo "Instalando Python 3.11 y dependencias..."
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip

# 2. Instalar Ollama en el sistema operativo
if ! command -v ollama &> /dev/null
then
    echo "Instalando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama ya está instalado."
fi

# 3. Crear y activar el entorno virtual forzando Python 3.11
echo "Configurando el entorno virtual con Python 3.11..."
python3.11 -m venv venv
source venv/bin/activate

# 4. Instalar los requerimientos de Python
echo "Instalando librerías de Python..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Descargar el modelo de Ollama
echo "Descargando modelo en Ollama..."
ollama pull llama2:7b-chat

echo "¡Todo listo! Para iniciar el bot ejecuta: source venv/bin/activate && python main.py"
# Si quieres levantar la web, ejecuta: source venv/bin/activate && chainlit run chainlit_app.py -w