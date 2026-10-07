#!/bin/bash

# Script de despliegue automatizado para SCADA Web
# Detiene contenedores, purga basura y levanta el entorno en limpio.

echo "================================================"
echo "    AGUAS DEL VALLE - DEPLOY AUTOMATIZADO"
echo "================================================"

# Cambiamos al directorio del script (donde está el docker compose.yml)
cd "$(dirname "$0")"

echo "[*] Deteniendo contenedores actuales y limpiando volúmenes huerfanos..."
docker compose down -v --remove-orphans

echo "[*] Limpiando imágenes antiguas del proyecto para forzar reconstrucción limpia..."
docker rmi aguas_del_valle_ctf scada_web-scada-web 2>/dev/null || true

echo "[*] Construyendo y levantando la base de datos MySQL y la Web SCADA..."
docker compose up -d --build

echo ""
echo "[*] ¡Despliegue exitoso!"
echo "[*] Contenedores activos:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "-> Web SCADA expuesta en: http://localhost:5000"
echo "-> MySQL interno expuesto en: localhost:3306"
