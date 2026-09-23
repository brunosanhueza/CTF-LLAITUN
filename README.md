# 💧 Aguas del Valle S.A. - CTF SCADA (IT/OT)

¡Bienvenido al entorno de simulación de **Aguas del Valle S.A.**! Este proyecto es un desafío tipo **Capture The Flag (CTF)** diseñado para entrenar habilidades de ciberseguridad en infraestructuras críticas (ICS/OT) e IT.

El sistema emula una planta de tratamiento y distribución de agua controlada por un entorno mixto: una interfaz web corporativa y un nodo industrial edge (simulando una Raspberry Pi y un PLC Modbus TCP).

---

## 🏗️ Arquitectura del Proyecto

El proyecto está diseñado usando una arquitectura de microservicios para separar la lógica de IT de la lógica de OT:

* 🌐 **`scada_web/` (Interfaz HMI e IT):** Contiene la aplicación Flask, el dashboard en modo Kiosko y los paneles de administración. Incluye su propio `Dockerfile` y `docker-compose.yml` para un despliegue aislado.
* ⚙️ **`nodo_raspberry/` (Control Edge OT):** Contiene el daemon (`rtu_daemon.py`) que representa la Raspberry Pi. Es el encargado de leer sensores físicos (ToF VL53L0X), manejar relés de bombas, monitorear la red Modbus y activar mecanismos de autoprotección.

---

## 🚀 Cómo ejecutar el simulador

El proyecto requiere Docker para la parte web y Python 3 para el nodo edge.

### 1. Levantar el Panel Web (SCADA HMI)
Navega a la carpeta web e inicia los contenedores. Esto levantará la aplicación Flask y preparará el entorno vulnerable:
```bash
cd scada_web
docker-compose up -d --build
```
> **Nota:** La interfaz web estará disponible en `http://localhost:5000`.

### 2. Levantar el Nodo Edge (Raspberry Pi / RTU)
En una terminal separada, inicia el simulador físico de hardware:
```bash
cd nodo_raspberry
pip install -r requirements.txt
python rtu_daemon.py
```

---

## 🚩 Objetivos del CTF (Kill Chain)

Los participantes deberán encadenar múltiples vulnerabilidades para lograr el objetivo final: **desbordar el estanque de agua y recuperar la bandera oculta (Flag) en la memoria del PLC.**

### Vulnerabilidades presentes:
1. **Acceso Inicial / Foothold:** Credenciales expuestas por defecto.
2. **Local File Inclusion (LFI):** Vulnerabilidad de *Path Traversal* en el módulo de descarga de bitácoras, permitiendo lectura de archivos arbitrarios del servidor (`/etc/passwd`).
3. **Escalada de Privilegios:** Sistema inseguro de carga de archivos de mantenimiento (`/portal/upload`).
4. **Fuga de Información Criptográfica:** Extracción del archivo binario `app.pyc` para hacer ingeniería inversa y robar la `SECRET_KEY` de Flask (Cookie Forging).
5. **Ataque OT (Modbus TCP Injection):** Sobrescritura de registros Modbus sin autenticación, que permite puentear (bypass) las rutinas de seguridad de la bomba y causar una inundación crítica.
6. **Volcado de Memoria PLC:** Lectura de bloques de *Holding Registers* Modbus para descifrar la Flag.

---


<img width="220" height="287" alt="hatsune-miku-dance" src="https://github.com/user-attachments/assets/46bdc174-4467-4487-972e-acab3ff54569" />

## ⚠️ Advertencia Legal y de Seguridad

Este entorno ha sido creado con fines **estrictamente educativos**. Contiene vulnerabilidades severas introducidas a propósito (como LFI, inyección insegura y exposición de claves). 
**NO DEBE ser desplegado en servidores públicos ni redes no controladas sin el aislamiento adecuado.**
