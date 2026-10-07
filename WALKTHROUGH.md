# 🗺️ Guía Oficial de Resolución (Walkthrough / Ruta de Ataque)
**Proyecto:** CTF Aguas del Valle S.A.
**Objetivo Final:** Desbordar la planta física y capturar la Web Flag oculta en el panel de administrador.

Esta es la ruta lógica exacta que un jugador debe seguir para hilar las vulnerabilidades. No hay "adivinanzas ciegas"; cada paso deja una "miga de pan" (pista) hacia el siguiente.

---

## 🔍 Paso 0: Reconocimiento Inicial
1. **Escaneo de Puertos:** El jugador escanea la IP objetivo (`nmap -sV <IP>`).
2. **Descubrimiento:** Encuentra el puerto `5000` (o `80`) abierto sirviendo una aplicación web Flask, y posiblemente el puerto `22` (SSH).
3. **Exploración Visual:** Entran por el navegador y se topan con el portal corporativo de "Aguas del Valle". El index los redirige a `/login`.

---

## 💉 Fase 1: SQL Injection y Acceso Inicial (El Foothold)
1. **El Vector:** En la página de `/login`, ven un recuadro abajo: *"Buscador Público de Operadores"*.
2. **La Prueba:** Buscan un nombre normal (ej: "Juan") y ven cómo la URL cambia a `/api/v1/search?query=Juan`.
3. **Explotación:** Prueban una comilla simple (`/api/v1/search?query='`) y la página arroja un error feo de SQL (`sqlite3.OperationalError` o similar).
4. **Extracción (Dump):** Usan `sqlmap` (`sqlmap -u "http://X.X.X.X:5000/api/v1/search?query=a" --dbs --dump`) o inyectan UNION SELECT manualmente.
5. **El Hallazgo:** Vuelcan la tabla `usuarios` y ven tres cuentas:
   - `op_turno1` (Hash muy largo, imposible de romper).
   - `admin_scada` (Hash complejo).
   - `testing` (Hash corto).
6. **Cracking:** Pasan el hash de `testing` por *Hashcat* o *John The Ripper* usando el diccionario `rockyou.txt`. En segundos, descubren que la contraseña es `sistemas12`.
7. **Resultado:** Inician sesión exitosamente en `/login` con `testing` / `sistemas12`.

---

## 📂 Fase 2: Fuzzing y Exfiltración LFI (El Pivote al Sistema Operativo)
1. **El Bloqueo:** Ya logueados en `/intranet`, la cuenta `testing` no tiene permisos administrativos. No hay botones de "Hackear Planta". Necesitan escalar.
2. **Fuzzing de Directorios:** Como buenos atacantes, usan `Dirb`, `Gobuster` o `Feroxbuster` contra la URL para buscar rutas ocultas.
3. **La Pista (Miga de Pan):** El fuzzer descubre una ruta oculta: `/api/v1/messages`.
4. **Lectura de la Pista:** Al entrar a `/api/v1/messages`, ven un log antiguo de conversación. Un mensaje dice:
   > *"Oye, te dejé tu llave SSH (id_rsa) temporal tirada en la carpeta oculta /uploads por error. El usuario del servidor Debian es operador_it, bórrala cuando entres."*
5. **El Ataque (LFI):** En el `/intranet` normal, hay una función para descargar bitácoras (ej. `/intranet/download?file=bitacora_1.pdf`). El jugador abusa de esta ruta inyectando un *Path Traversal* (Local File Inclusion):
   - Payload: `/intranet/download?file=../../uploads/id_rsa`
6. **Resultado:** Descargan exitosamente la llave privada SSH.

---

## 🛡️ Fase 3: Escalada de Privilegios a Root (El Pwn de Host)
1. **Conexión SSH:** Usan la llave robada para entrar al servidor:
   - `chmod 600 id_rsa`
   - `ssh -i id_rsa operador_it@<IP>`
2. **El Bloqueo:** Intentan usar Docker (`docker ps`), pero obtienen *Permission Denied*. Son un usuario de bajos privilegios.
3. **Enumeración del Sistema:** Ejecutan los comandos básicos de post-explotación. Al lanzar `sudo -l` para ver qué permisos especiales tienen, notan algo brillante:
   - `(root) NOPASSWD: /opt/scripts/restart_scada.sh`
4. **La Mala Configuración:** Revisan el archivo con `ls -la /opt/scripts/restart_scada.sh` y se dan cuenta de que el archivo pertenece a su mismo usuario (`operador_it`). **Tienen permisos de escritura.**
5. **El Exploit:** Modifican el archivo inyectando una shell en su interior:
   - `echo "/bin/bash" >> /opt/scripts/restart_scada.sh`
6. **Ejecución:** Corren `sudo /opt/scripts/restart_scada.sh`.
7. **Resultado:** Al ejecutarse con privilegios de administrador, se levanta la terminal root. **Obtienen prompt `#` (root en el host).**

---

## ⚡ Fase 4: Impacto OT e Inundación (Sabotaje Modbus)
1. **Reconocimiento Interno:** Siendo `root`, ahora pueden ver todo. Observan que existe un puerto `502` abierto en la red interna (la IP de la Raspberry Pi / PLC).
2. **Manual Técnico:** Recuerdan que en la web (Fase 1), había un "Manual Técnico del PLC" descargable que indicaba:
   - *Registro 0:* Control de Estado (Fuerza la bomba y apaga el sensor).
3. **El Ataque Cibercinético:** Desde la consola root de Linux, usan un cliente por terminal (como `modbus-cli` o un script corto en Python) para inyectar una trama Modbus directamente al PLC:
   - Comando conceptual: `Escribir Registro Holding 0 = 768 (0x0300)`.
4. **Resultado Físico:** (En la vida real de tu maqueta) Las bombas se encienden sin parar, el sensor láser es ignorado, el dashboard público grita "INUNDACIÓN CRÍTICA" en rojo. *¡Caos en la planta!*

---

## 🏴‍☠️ Fase 5: El "Trofeo de Vuelta" (Pivote de Docker a Web Flag)
1. **La Meta Final:** El CTF exige capturar la Flag en formato texto `CtF_L1@I7uN{...}`. El panel de administrador en la web dice que la Flag está cifrada adentro, pero necesitan iniciar sesión como `admin_scada` para verla.
2. **El Bloqueo:** Como el código de Python de la web está ofuscado, no pueden simplemente hacer `cat app.py` para robar secretos o forzar cookies.
3. **El Abuso de Docker:** Como son `root` en el host, tienen poder sobre Docker. Corren `docker ps` y ven el contenedor de la base de datos `mysqlbd`.
4. **Robo de Credenciales DB:** Corren `docker inspect mysqlbd` y extraen de las Variables de Entorno la clave de root de MySQL.
5. **Inyección Directa en DB:** Entran al contenedor de base de datos en vivo:
   - `docker exec -it mysqlbd mysql -u root -p`
6. **El Hijacking:** Hacen un UPDATE en la base de datos para machacar la contraseña in-crackeable del admin por una propia:
   - `UPDATE usuarios SET password_hash = '<hash_creado_por_el_hacker>' WHERE username = 'admin_scada';`
7. **Victoria:** El jugador vuelve a su navegador web, inicia sesión con `admin_scada` y la nueva clave, y el panel web le otorga la victoria renderizando la codiciada Flag. 🏆
