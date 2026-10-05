# 🎯 Kill Chain: CTF Aguas del Valle S.A.
*(Guía de Arquitectura de Red y Flujo de Explotación)*

## 🗺️ 1. Topología y Componentes de Red (Para pfSense / Diagrama)

El entorno se divide en tres zonas separadas por el firewall (pfSense):
1. **Red WAN / Atacante:** El exterior (Internet o VPN de jugadores).
2. **Red IT (Corporativa):** Servidor Debian Host + Contenedores Docker.
3. **Red OT (Industrial):** Maqueta física con la Raspberry Pi (totalmente aislada).

### Inventario de Puertos y Servicios
**Servidor Host (Debian Linux - Red IT)**
*   **Servicio 1:** SSH (Puerto TCP `22`).
*   **Servicio 2:** Docker Daemon (Socket interno `/var/run/docker.sock`).
*   **Contenedor A (`scada_web`):** Aplicación Flask. Expuesta a WAN por el puerto TCP `5000` (HTTP).
*   **Contenedor B (`mysqlbd`):** Base de Datos. Puerto TCP `3306` (Comunicación interna directa con Flask, no expuesto a WAN).

**Nodo Físico Edge (Raspberry Pi - Red OT)**
*   **Servicio:** Demonio RTU Python / PLC Simulado.
*   **Puerto:** TCP `502` (Modbus TCP).
*   **Hardware Conectado:** Relés (Bombas de agua 12V), Sensor I2C VL53L0X (Láser de distancia), Tiras LED WS2812B.

---

## 🔗 2. Flujo de Ataque Paso a Paso (La Kill Chain)

### 🟢 FASE 1: Infiltración Web (SQL Injection)
*   **Origen:** Atacante (WAN)
*   **Destino:** Debian Host -> `scada_web` (Puerto 5000) -> `mysqlbd` (Puerto 3306)
*   **Acción:** El tráfico HTTP entra al endpoint `/api/v1/search`. El contenedor Flask envía una consulta SQL cruda al contenedor MySQL. El atacante roba el hash de la cuenta `testing`, lo rompe offline (diccionario) y logra acceso al panel web.

### 🟡 FASE 2: Fuzzing y Path Traversal (Robo LFI)
*   **Origen:** Atacante (WAN)
*   **Destino:** Debian Host -> `scada_web` (Puerto 5000)
*   **Acción:** El atacante hace fuzzing y descubre la ruta oculta `/internal/messages` (pista). Luego, lanza un ataque LFI hacia `/intranet/download?file=...` para leer el archivo interno del contenedor `/var/backups/credenciales_ot.bak`.
*   **Loot:** Descifra el contenido (ROT47) para obtener la **[FLAG 1]** y las credenciales SSH válidas para el sistema operativo.

### 🟠 FASE 3: Salto Lateral y Escalada (Pivote de Red)
*   **Origen:** Atacante (WAN)
*   **Destino:** Servidor Debian Host (Puerto 22)
*   **Acción:** Cambio de protocolo y Capa. El atacante conecta por SSH usando las credenciales robadas (`operador_it`).
*   **Escalada (Local):** Ya dentro del servidor, ejecuta `sudo -l` y encuentra un script mal configurado con permisos de escritura. Inyecta el comando `/bin/bash` al final del script y escala a privilegios de **Root**.

### 🔴 FASE 4: El Impacto Cibercinético (Sabotaje SCADA)
*   **Origen:** Servidor Debian Host (El Atacante como Root)
*   **Destino:** Raspberry Pi en Red OT (Puerto 502)
*   **Acción:** El atacante pivota desde la red IT hacia la red OT. Envía paquetes **Modbus TCP** al puerto 502 de la Raspberry Pi escribiendo el valor `768` en el Registro 0.
*   **Loot:** La Raspberry desborda físicamente el agua e ilumina todo en rojo ("INUNDACIÓN CRÍTICA"). El atacante lee de vuelta los registros Modbus para capturar la **[FLAG 2]** que el demonio acaba de escribir en memoria.

### 🟣 FASE 5: El "Trofeo de Vuelta" (Post-Explotación Docker)
*   **Origen:** Servidor Debian Host (El Atacante como Root)
*   **Destino:** Contenedor `mysqlbd` (Vía Socket Docker) -> `scada_web` (Puerto 5000)
*   **Acción:** Como Root, el atacante usa comandos `docker exec` para entrar directamente a la memoria viva de MySQL y sobrescribe el hash del administrador con uno que él inventa. 
*   **Cierre:** El atacante vuelve a hacer una conexión web desde su máquina (WAN) al Puerto 5000, inicia sesión como Admin y la interfaz web desencripta y renderiza la **[FLAG 3]**.

---

## 🛡️ 3. Reglas de Enrutamiento en pfSense (El Candado del CTF)
Para que el diseño de esta máquina sea realista y obligue al jugador a seguir todas las fases sin saltarse pasos, el firewall pfSense debe cumplir estas 3 reglas estrictas:

1. **Permitir a WAN -> IT:** El atacante externo solo puede acceder a la IP del servidor Debian por los puertos **5000 (HTTP)** y **22 (SSH)**.
2. **Bloquear WAN -> OT:** El atacante **NO TIENE** acceso directo a la IP de la Raspberry Pi. Las peticiones directas desde el exterior al puerto 502 deben ser dropeadas.
3. **Permitir IT -> OT:** El servidor Debian **SÍ TIENE** permisos para enviar tráfico al puerto 502 de la Raspberry Pi.
*(Esta configuración obliga al hacker a vulnerar el servidor Debian corporativo para usarlo obligatoriamente como un puente o pivote hacia la infraestructura física).*
