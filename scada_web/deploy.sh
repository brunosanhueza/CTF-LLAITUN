#!/bin/bash
set -e

# ==============================================================================
# AGUAS DEL VALLE S.A. - DESPLIEGUE MAESTRO UNIFICADO (HOST & DOCKER)
# Ejecutar como ROOT en el servidor Debian del CTF:
#   chmod +x deploy.sh
#   sudo ./deploy.sh
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "[!] ERROR: Este script debe ejecutarse como root (con privilegios sudo):"
    echo "    sudo ./deploy.sh"
    exit 1
fi

echo "=================================================="
echo "    AGUAS DEL VALLE - DEPLOY MAESTRO UNIFICADO   "
echo "=================================================="

# ------------------------------------------------------------------------------
# FASE 1: CONFIGURACIÓN Y HARDENING DEL HOST DEBIAN
# ------------------------------------------------------------------------------
echo ""
echo "[FASE 1/2] Configurando el Host Debian (Usuarios, PrivEsc, Firewall, Camuflaje)..."

# 1. Crear usuario operador_it si no existe
if ! id -u operador_it > /dev/null 2>&1; then
    echo "  [+] Creando usuario del sistema 'operador_it'..."
    useradd -m -s /bin/bash operador_it
else
    echo "  [*] El usuario 'operador_it' ya existe."
fi

# Configurar credencial real obtenida del Base64
echo "operador_it:CiB3R1Ab{0P3R4DOR2026_67}" | chpasswd
echo "  [+] Contraseña de 'operador_it' configurada con éxito."

# 2. Instalar gcc si no existe y configurar Escalada de Privilegios (PrivEsc via sudo gcc)
if ! command -v gcc >/dev/null 2>&1 || [ ! -x "/usr/bin/gcc" ]; then
    echo "  [+] Instalando paquete 'gcc' para el vector de escalada de privilegios..."
    apt-get update -y && apt-get install -y --no-install-recommends gcc
fi

echo "  [+] Configurando permisos de Sudoers (gcc wrapper)..."
echo "operador_it ALL=(root) NOPASSWD: /usr/bin/gcc" > /etc/sudoers.d/operador_it
chmod 0440 /etc/sudoers.d/operador_it

# 3. Reglas de Firewall (iptables): Bloquear al PLC (10.10.30.103) para no-root
echo "  [+] Aplicando reglas de firewall local (iptables)..."
iptables -D OUTPUT -d 10.10.30.103 -m owner ! --uid-owner 0 -j REJECT 2>/dev/null || true
iptables -A OUTPUT -d 10.10.30.103 -m owner ! --uid-owner 0 -j REJECT

# Persistir reglas de iptables si la herramienta existe
if command -v netfilter-persistent > /dev/null 2>&1; then
    netfilter-persistent save > /dev/null 2>&1 || true
elif command -v iptables-save > /dev/null 2>&1; then
    mkdir -p /etc/iptables
    iptables-save > /etc/iptables/rules.v4
fi
echo "  [+] Tráfico al PLC (10.10.30.103) bloqueado para usuarios sin privilegios."

# 4. Camuflaje del Puerto 22 (SSH activo pero invisible en ss y netstat)
echo "  [+] Instalando camuflaje de visualización para el puerto 22..."
cat << 'EOF' > /usr/local/bin/ss
#!/bin/bash
real_ss="/usr/bin/ss"
[ ! -f "$real_ss" ] && real_ss="/bin/ss"
"$real_ss" "$@" | grep -vE '(:22\s|:ssh\s|\b22\b.*sshd)'
EOF
chmod 755 /usr/local/bin/ss

if command -v netstat >/dev/null 2>&1; then
    real_netstat=$(which netstat)
    if [ "$real_netstat" != "/usr/local/bin/netstat" ]; then
        cat << EOF > /usr/local/bin/netstat
#!/bin/bash
$real_netstat "\$@" | grep -vE '(:22\s|:ssh\s|\b22\b.*sshd)'
EOF
        chmod 755 /usr/local/bin/netstat
    fi
fi
echo "  [+] Puerto 22 camuflado (oculto en ss y netstat incluso para root)."

# 5. Purga y deshabilitación permanente del historial de Bash (Anti-Spoil CTF)
echo "  [+] Deshabilitando y enlazando historial de comandos a /dev/null..."
cat << 'EOF' > /etc/profile.d/disable_history.sh
#!/bin/bash
unset HISTFILE
export HISTSIZE=0
export HISTFILESIZE=0
export HISTFILE=/dev/null
set +o history
EOF
chmod 644 /etc/profile.d/disable_history.sh

if ! grep -q "HISTFILE=/dev/null" /etc/bash.bashrc 2>/dev/null; then
    cat << 'EOF' >> /etc/bash.bashrc
unset HISTFILE
export HISTSIZE=0
export HISTFILESIZE=0
export HISTFILE=/dev/null
set +o history
EOF
fi

# Eliminar archivos existentes y crear enlace simbólico a /dev/null
rm -f /root/.bash_history
ln -sf /dev/null /root/.bash_history

for u_dir in /home/*; do
    if [ -d "$u_dir" ]; then
        rm -f "$u_dir/.bash_history"
        ln -sf /dev/null "$u_dir/.bash_history"
    fi
done

# Limpiar buffer de sesión en memoria
history -c 2>/dev/null || true
history -w 2>/dev/null || true
echo "  [+] Historial de bash purgado y enlazado a /dev/null con éxito."

# ------------------------------------------------------------------------------
# FASE 2: DESPLIEGUE DE CONTENEDORES DOCKER
# ------------------------------------------------------------------------------
echo ""
echo "[FASE 2/2] Desplegando Contenedores Docker (Web SCADA + MySQL)..."
cd "$(dirname "$0")"

echo "  [*] Deteniendo contenedores previos y limpiando volúmenes huérfanos..."
docker compose down -v --remove-orphans 2>/dev/null || docker-compose down -v --remove-orphans 2>/dev/null || true

echo "  [*] Limpiando imágenes antiguas para forzar reconstrucción limpia..."
docker rmi aguas_del_valle_ctf scada_web-scada-web 2>/dev/null || true

echo "  [*] Compilando y levantando contenedores en segundo plano..."
if docker compose version >/dev/null 2>&1; then
    docker compose up -d --build
else
    docker-compose up -d --build
fi

echo ""
echo "=================================================="
echo "      ¡DESPLIEGUE INTEGRAL COMPLETADO CON ÉXITO!   "
echo "=================================================="
echo "[*] Contenedores activos en el sistema:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "-> Web SCADA activa en:  http://localhost:5000"
echo "-> MySQL interno en:     localhost:3306"
echo "-> SSH Host configurado: puerto 22 (usuario 'operador_it')"
echo "-> PrivEsc listo:        'sudo gcc -wrapper /bin/sh,-s x'"
echo "-> PLC protegido:        10.10.30.103 accesible únicamente para root y Docker"
echo "=================================================="
