#!/bin/bash

# ==============================================================================
# SCRIPT DE CONFIGURACIÓN DEL HOST DEBIAN (MÁQUINA VÍCTIMA)
# Ejecutar como ROOT en el servidor Debian donde los atacantes entran por SSH
# ==============================================================================

echo "[*] Configurando el Host Debian para el CTF..."

# 1. Crear el usuario operador_it si no existe
if ! id -u operador_it > /dev/null 2>&1; then
    echo "[*] Creando usuario 'operador_it'..."
    useradd -m -s /bin/bash operador_it
fi

# Configurar su contraseña real (la del Base64)
echo "operador_it:CiB3R1Ab{0P3R4DOR2026_67}" | chpasswd

# 2. Configurar la Escalada de Privilegios (PrivEsc)
# Permitimos a operador_it correr GCC como root sin contraseña
echo "[*] Configurando Sudoers para PrivEsc (gcc wrapper)..."
echo "operador_it ALL=(root) NOPASSWD: /usr/bin/gcc" > /etc/sudoers.d/operador_it
chmod 0440 /etc/sudoers.d/operador_it

# 3. Bloquear el acceso a Modbus (502) para usuarios sin privilegios
# Esto asegura que tengan que escalar a root para atacar el PLC.
# La cadena OUTPUT solo afecta a procesos locales, por lo que el contenedor 
# Docker (que pasa por la cadena FORWARD) no se verá afectado y seguirá funcionando.
echo "[*] Aplicando reglas de firewall local (iptables)..."

# Limpiar regla previa si ya existía para no duplicar
iptables -D OUTPUT -d 10.10.30.103 -m owner ! --uid-owner 0 -j REJECT 2>/dev/null

# Bloqueo TOTAL hacia el PLC (10.10.30.103): Corta TCP (80, 102, 502), UDP e ICMP (Ping)
# Ningún usuario sin privilegios puede ver ni interactuar con el PLC hasta ser root (UID 0)
iptables -A OUTPUT -d 10.10.30.103 -m owner ! --uid-owner 0 -j REJECT

# 4. Ocultar el puerto 22 a herramientas de inspección (ss, netstat, lsof)
# El servicio SSH sigue funcionando al 100%, pero no aparecerá en 'ss -tuln' ni 'netstat -tuln'
# incluso si los comandos son ejecutados como root.
echo "[*] Configurando camuflaje para ocultar el puerto 22 en la inspección local..."

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

# 5. Hacer que las reglas persistan tras un reinicio (Opcional pero recomendado)
echo "[*] Guardando reglas de iptables..."
if command -v netfilter-persistent > /dev/null; then
    netfilter-persistent save
elif command -v iptables-save > /dev/null; then
    mkdir -p /etc/iptables
    iptables-save > /etc/iptables/rules.v4
fi

echo "[*] ¡Configuración del Host terminada con éxito!"
echo "-> PrivEsc configurado: 'sudo gcc' habilitado para operador_it."
echo "-> Red restringida: Solo 'root' y 'Docker' pueden hablar con el PLC (10.10.30.103)."
echo "-> Puerto 22 camuflado: SSH activo pero oculto en 'ss' y 'netstat' (incluso para root)."
