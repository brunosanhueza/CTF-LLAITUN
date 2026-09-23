# 📘 DOCUMENTACIÓN DEL PROYECTO: AGUAS DEL VALLE S.A.
### Sistema SCADA HMI, Telemetría en Tiempo Real & Reto CTF (IT/OT)

Este proyecto simula una planta de tratamiento y distribución de agua montada sobre una **maqueta a escala de una ciudad**. Utiliza una **Raspberry Pi 4 Model B**, un sensor de tiempo de vuelo **VL53L0X**, un **PLC industrial** (Modbus TCP) que manipula un **servomotor/bomba**, y una pantalla táctil de 9" configurada en modo estático (Kiosk).

---

## 👥 1. Usuarios y Credenciales del Sistema

La base de datos (`database/db.py`) viene precargada con dos usuarios para simular los roles de la empresa:

| Usuario | Contraseña | Rol | Acceso y Privilegios |
| :--- | :--- | :--- | :--- |
| **`operador`** | `operador2026` | `operador` | Acceso a `/portal`. Puede ver bitácoras de turno, leer el manual técnico del PLC y subir reportes de mantenimiento. |
| **`admin_scada`** | `Adm1n_Pl4nt4_S3cur3!#` | `admin` | Acceso total a `/admin`. Control de la **Consola Modbus Raw** para escribir y leer registros directamente en el PLC. |

---

## 🌐 2. Catálogo Completo de Endpoints

### 🔐 A. Autenticación y Navegación

* **`GET /`**
  * **Función:** Enrutador inteligente. Si hay una sesión activa de `admin`, redirige a `/admin`. Si hay sesión de `operador`, redirige a `/portal`. Si no hay sesión, redirige a `/login`.
* **`GET /login` | `POST /login`**
  * **Función:** Portal de inicio de sesión corporativo. Valida credenciales contra MySQL (o SQLite) y establece cookies de sesión cifradas.
* **`GET /logout`**
  * **Función:** Destruye la sesión del usuario y redirige al login con mensaje informativo.

---

### 👷 B. Portal del Operador

* **`GET /portal`**
  * **Seguridad:** Requiere inicio de sesión (`@login_required`).
  * **Función:** Muestra el perfil del técnico, el **Manual de Operaciones Modbus del PLC** (mapa de registros), el historial de bitácoras registradas y el formulario de carga de reportes.
* **`POST /portal/upload`**
  * **Seguridad:** Requiere inicio de sesión (`@login_required`).
  * **Función:** Recibe reportes y archivos adjuntos (`.txt`, `.pdf`, `.py`, `.sh`).
  * **🎯 Vector de Escalada CTF:** Si el archivo contiene una directiva de mantenimiento (`ELEVATE_ROLE=admin`, `ADMIN_OVERRIDE_AUTH`) o tiene extensión ejecutable, el backend promueve automáticamente al usuario a rol `admin` en la base de datos.

---

### ⚙️ C. Panel de Ingeniería SCADA (Admin)

* **`GET /admin`**
  * **Seguridad:** Requiere rol de administrador (`@admin_required`).
  * **Función:** Panel de control de ingeniería con la **Consola de Transmisión Modbus TCP Raw**.
* **`POST /api/admin/modbus_raw`**
  * **Seguridad:** Requiere rol de administrador (`@admin_required`).
  * **Parámetros JSON:**
    ```json
    {
      "function_code": "0x06",
      "register": 0,
      "value": "768"
    }
    ```
  * **Función:** Envía tramas Modbus binarias directas al PLC (`192.168.60.10:502`).
    * **FC `0x06` (Write Single Register):** Escribe un valor en el registro indicado.
    * **FC `0x03` (Read Holding Registers):** Lee un bloque de registros.
  * **Mecánica CTF:** Al escribir `768` (`0x0300`) en el Registro `0`, se anula el límite de seguridad del sensor ToF provocando el desborde del estanque. Al leer 16 registros desde el Registro 1, se recupera el *Factory Root ID* (la Flag).

---

### ⚡ D. Control de Relé Físico & Actuadores (Raspberry Pi GPIO 4)

* **`GET /api/rele/estado`**
  * **Función:** Retorna el estado en tiempo real del relé de hardware (GPIO 4 / Pin 7), la conexión con el PLC en `10.10.10.4:502` y el valor actual del Registro Modbus (Offset 9).
* **`POST /api/rele/control`**
  * **Parámetros JSON:**
    ```json
    {
      "accion": "iniciar" | "detener" | "toggle" | "reconfigurar",
      "plc_ip": "10.10.10.4",
      "port": 502,
      "registro": 9,
      "pin_rele": 4,
      "intervalo": 0.5
    }
    ```
  * **Función:** Inicia o detiene el bucle de monitoreo continuo en segundo plano, o reconfigura dinámicamente los parámetros de conexión con el PLC y el pin GPIO de la Raspberry Pi.
* **`POST /api/rele/accion`**
  * **Parámetros JSON (opcional):** `{"activar": true | false}`
  * **Función:** Conmuta directamente el estado físico del relé conectado al Pin GPIO 4.

---

### 📊 E. Monitor Público del Estanque & Telemetría

* **`GET /dashboard`**
  * **Acceso:** **Público** (Sin autenticación).
  * **Diseño:** **Modo Kiosk (100vh estático, 0 scroll)** optimizado para la pantalla de 9" de la maqueta.
  * **Función:** Diagrama P&ID vectorial SVG interactivo que muestra en tiempo real:
    * Nivel de agua dinámico con ondas y cambio de color (Azul $\to$ Amarillo $\to$ Rojo peligro).
    * Sensor ToF VL53L0X con haz láser proyectado y cota milimétrica.
    * Aspas de bomba girando y flujo en tuberías.
    * Efecto visual de desborde/inundación.
    * Tarjetas de nivel, distancia ToF, estado de bomba y botón de reseteo.
* **`GET /api/telemetria`**
  * **Función:** Devuelve el JSON con el estado instantáneo del estanque.
* **`POST /api/reset`**
  * **Función:** Restablece la simulación y registros Modbus a valores nominales limpios.
* **`GET /api/modbus`**
  * **Función:** Endpoint legado de inyección rápida para pruebas automáticas.

---

## ⚡ 3. Eventos WebSockets (Socket.IO)

El backend emite y recibe eventos en tiempo real con latencia cero:

| Evento | Dirección | Descripción |
| :--- | :--- | :--- |
| `telemetria` | Servidor $\to$ Cliente | Emite cada 200ms (5 Hz) el paquete con nivel %, distancia mm, bomba ON/OFF, ángulo servo, bypass y alarmas. |
| `inundacion_detectada` | Servidor $\to$ Cliente | Se dispara al superar el 98% de nivel; envía la Flag decodificada a la interfaz. |
| `reset_sistema` | Cliente $\to$ Servidor | Restablece el estanque y los registros Modbus desde la interfaz táctil. |

---

## 📁 4. Estructura del Código Fuente

```text
ctf-agua-26/
├── app.py                      # Servidor Flask principal, rutas y WebSockets
├── DOCUMENTACION.md            # Este documento técnico
├── database/
│   ├── __init__.py
│   └── db.py                  # Conexión MySQL / SQLite, hashing y modelos
├── servicios/
│   ├── __init__.py
│   ├── sensor_tof.py          # Driver del sensor VL53L0X con física simulada
│   ├── modbus_service.py      # Cliente Modbus TCP y memoria del PLC
│   └── scada_engine.py        # Motor SCADA de control y enclavamiento de seguridad
├── comandos_gpio/
│   ├── __init__.py
│   └── luces.py              # Control de LEDs de estado en Raspberry Pi
├── templates/
│   ├── login.html             # Login corporativo
│   ├── portal.html            # Portal del operador y manual técnico
│   ├── admin.html             # Panel de ingeniería con Consola Modbus Raw
│   └── dashboard.html         # Monitor Kiosk 100vh del estanque
├── static/
│   ├── css/
│   │   └── static.css         # Estilos industriales, P&ID y modo Kiosk
│   └── js/
│       ├── main.js            # Lógica del login y terminal
│       ├── admin.js           # Lógica interactiva de la Consola Modbus Raw
│       └── dashboard.js       # Animación SVG y WebSockets del estanque
└── uploads/                   # Carpeta de almacenamiento de archivos subidos
```

---

## 🚩 5. Guía de Solución del Reto CTF (Walkthrough)

1. **Paso 1: Acceso Inicial**
   * Ingresar a `http://localhost:5000/login` con `operador` / `operador2026`.
2. **Paso 2: Reconocimiento del PLC**
   * En `/portal`, leer el **Manual Técnico del PLC**. Descubrir que:
     * `Registro 0 = 0x0300 (768)`: Fuerza la apertura de la bomba y anula el sensor ToF.
     * `Registros 1 al 16`: Bloque de diagnóstico protegido (donde está la Flag).
3. **Paso 3: Escalada de Privilegios**
   * En `/portal`, ir a **Cargar Reporte de Turno**.
   * Subir un archivo de texto con el payload `ELEVATE_ROLE=admin` o un script `.py`.
   * El sistema promueve al usuario a `admin` y desbloquea el botón `[⚙️ Panel Admin SCADA]`.
4. **Paso 4: Inyección Modbus Raw**
   * Ir a `/admin` $\to$ **Consola Modbus Raw**.
   * Parámetros:
     * **Función:** `0x06 - Escribir Registro Individual`
     * **Registro:** `0`
     * **Valor:** `768` (o `0x0300`)
   * Presionar **Transmitir Trama**.
   * El PLC recibe la orden, la bomba se enciende al 100% y el sensor ToF queda anulado.
5. **Paso 5: Desborde y Captura de Flag**
   * En `/dashboard`, el agua sube sin cortar en 85%, llega al 100% y se desborda (`INUNDACIÓN CRÍTICA`).
   * En la Consola de `/admin`, seleccionar:
     * **Función:** `0x03 - Leer Registros de Retención`
     * **Registro:** `1`
     * **Cantidad:** `16`
   * Presionar **Transmitir**.
   * La consola decodifica la memoria en ASCII y entrega la Flag:
     ```text
     CTF{0v3rfl0w_m0dbus_sc4d4_pwn3d}
     ```

---

## 🚀 6. Cómo Ejecutar el Servidor

```bash
# 1. Iniciar servidor Flask con Socket.IO
./venv/bin/python app.py

# 2. Acceder desde navegador
# Portal Web:     http://localhost:5000
# Monitor Kiosk:  http://localhost:5000/dashboard
```
