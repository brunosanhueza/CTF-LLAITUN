#!/bin/bash
# Script para configurar la vulnerabilidad de Sudo (Escalada de Privilegios) en el servidor host

echo "[*] Configurando el escenario de escalada de privilegios..."

# 1. Asegurar que existe el usuario operador_it (solo para pruebas, en el CTF real ya debería existir)
if ! id "operador_it" &>/dev/null; then
    echo "[*] Creando usuario operador_it..."
    sudo useradd -m -s /bin/bash operador_it
    echo "operador_it:operador2026" | sudo chpasswd
fi

# 2. Crear el directorio de scripts
echo "[*] Creando /opt/scripts..."
sudo mkdir -p /opt/scripts
sudo chown root:root /opt/scripts
sudo chmod 755 /opt/scripts

# 3. Crear el script de reinicio SCADA
echo "[*] Creando el script restart_scada.sh..."
cat << 'EOF' | sudo tee /opt/scripts/restart_scada.sh > /dev/null
#!/bin/bash
echo "============================================="
echo " AGUAS DEL VALLE - REINICIO DE SERVICIOS OT  "
echo "============================================="
echo "[+] Deteniendo servicios Modbus en Edge Node..."
sleep 1
echo "[+] Reiniciando contenedores Docker web..."
# docker-compose restart scada-web (Simulado)
sleep 1
echo "[+] Servicios SCADA reiniciados exitosamente."
EOF

# 4. Asignar permisos débiles (VULNERABILIDAD)
# Hacemos que el dueño sea operador_it para que tenga permiso de escritura
echo "[*] Configurando permisos vulnerables (escritura para operador_it)..."
sudo chown operador_it:operador_it /opt/scripts/restart_scada.sh
sudo chmod 744 /opt/scripts/restart_scada.sh

# 5. Configurar Sudoers para permitir la ejecución sin contraseña
echo "[*] Configurando sudoers (/etc/sudoers.d/ctf_escalation)..."
echo "operador_it ALL=(root) NOPASSWD: /opt/scripts/restart_scada.sh" | sudo tee /etc/sudoers.d/ctf_escalation > /dev/null
sudo chmod 440 /etc/sudoers.d/ctf_escalation

echo "[+] ¡Vulnerabilidad de Sudo configurada con éxito!"
echo "[+] Para probarla:"
echo "    1. su - operador_it"
echo "    2. sudo -l"
echo "    3. echo '/bin/bash' >> /opt/scripts/restart_scada.sh"
echo "    4. sudo /opt/scripts/restart_scada.sh"
