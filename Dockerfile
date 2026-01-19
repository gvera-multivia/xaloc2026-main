# Usar la imagen oficial de Playwright con Python
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Evitar prompts durante la instalación
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema y Microsoft Edge
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    libnss3-tools \
    && curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg \
    && install -o root -g root -m 644 microsoft.gpg /etc/apt/trusted.gpg.d/ \
    && echo "deb [arch=amd64] https://packages.microsoft.com/repos/edge stable main" > /etc/apt/sources.list.d/microsoft-edge-dev.list \
    && rm microsoft.gpg \
    && apt-get update && apt-get install -y microsoft-edge-stable \
    && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar requerimientos e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Preparar directorios de persistencia
RUN mkdir -p db logs screenshots profiles/worker auth

# Hacer el entrypoint ejecutable
RUN chmod +x entrypoint.sh

# El entrypoint se encargará de importar el certificado antes de lanzar el worker
ENTRYPOINT ["./entrypoint.sh"]
