#!/bin/bash
# Script para compilar e instalar el binario vulnerable en el servidor Ubuntu

echo "[*] Compilando plc_diagnostic.c sin protecciones (Ret2Libc target)..."
# -fno-stack-protector: Quita el "canario" que detecta desbordamientos
# -no-pie: Mantiene las direcciones de memoria del binario estáticas (fáciles de calcular)
gcc plc_diagnostic.c -o plc_diagnostic -fno-stack-protector -no-pie

echo "[*] Moviendo el binario a /usr/local/bin/"
sudo mv plc_diagnostic /usr/local/bin/

echo "[*] Configurando el dueño a 'root' y aplicando el bit SUID (4755)..."
sudo chown root:root /usr/local/bin/plc_diagnostic
sudo chmod 4755 /usr/local/bin/plc_diagnostic

echo "[+] ¡Listo! El binario vulnerable está instalado."
echo "    Puedes verificarlo con: ls -la /usr/local/bin/plc_diagnostic"
echo "    Debería verse rojo en la terminal y tener permisos: -rwsr-xr-x"
