# ==============================================================================
# Dockerfile - AGUAS DEL VALLE S.A. (CTF Challenge Web Application)
# ==============================================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PLC_HOST=192.168.60.10 \
    DB_TYPE=mysql \
    MYSQL_HOST=host.docker.internal \
    MYSQL_PORT=3306 \
    MYSQL_USER=root \
    MYSQL_PASSWORD=zacky5023 \
    MYSQL_DB=aguas_del_valle

WORKDIR /app

# Dependencias minimas del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    findutils \
    && rm -rf /var/lib/apt/lists/*

# Instalar librerias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar aplicacion completa
COPY . .

# Compilar a bytecode (.pyc) y purgar archivos fuente .py
RUN python -m compileall -b . && \
    find . -type f -name "*.py" -delete && \
    rm -rf /root/.cache

# Crear usuario seguro sin privilegios
RUN useradd -m -u 1001 scadauser && \
    mkdir -p /app/uploads && \
    chown -R scadauser:scadauser /app

USER scadauser

EXPOSE 5000

# Iniciar servicio web SCADA
CMD ["python", "app.pyc"]
