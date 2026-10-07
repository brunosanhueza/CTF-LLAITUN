import re

def update_daemon(file_path, is_test):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update HardwareManager init for sensor logs
    if is_test:
        old_init = """                # CODIGO MODIFICADO Y ADAPTADO DESDE C3-PLC: 
                # El sensor del Estanque 1 (Canal 2, bornera J20) esta malo fisicamente y cuelga el I2C.
                # Lo inicializaremos como None.
                for canal in [0, 1, 2, 3]:
                    if canal == 2:  # Estanque 1 roto
                        self.sensores.append(None)
                    else:
                        try:
                            sensor = VL53L0X(self.mux[canal])
                            self.sensores.append(sensor)
                        except Exception:
                            self.sensores.append(None)"""
                            
        new_init = """                # CODIGO MODIFICADO Y ADAPTADO DESDE C3-PLC: 
                # El sensor del Estanque 1 (Canal 2, bornera J20) esta malo fisicamente y cuelga el I2C.
                # Lo inicializaremos como None.
                logger.info("Iniciando escaneo de sensores I2C (Modo Test - Bypass Canal 2)...")
                for canal in [0, 1, 2, 3]:
                    if canal == 2:  # Estanque 1 roto
                        self.sensores.append(None)
                        logger.warning(f"[-] Canal {canal} IGNORADO intencionalmente por bypass.")
                    else:
                        try:
                            sensor = VL53L0X(self.mux[canal])
                            self.sensores.append(sensor)
                            logger.info(f"[+] Sensor en Canal {canal} INICIALIZADO correctamente.")
                        except Exception as e:
                            self.sensores.append(None)
                            logger.error(f"[X] FALLO CRITICO: El sensor en Canal {canal} NO RESPONDE via I2C ({e})")"""
    else:
        old_init = """                for canal in CANALES_SENSORES:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                    except Exception:
                        self.sensores.append(None)"""
                        
        new_init = """                logger.info("Iniciando escaneo de sensores I2C...")
                for canal in CANALES_SENSORES:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                        logger.info(f"[+] Sensor en Canal {canal} INICIALIZADO correctamente.")
                    except Exception as e:
                        self.sensores.append(None)
                        logger.error(f"[X] FALLO CRITICO: El sensor en Canal {canal} NO RESPONDE via I2C ({e})")"""
                        
    content = content.replace(old_init, new_init)

    # 2. Add continuous logging to the control loop
    old_loop_start = """    def _bucle_control(self):
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self._estado_bombas_local)
                
                if not self.cliente.is_open:
                    self.cliente.open()

                if self.cliente.is_open:"""
                
    new_loop_start = """    def _bucle_control(self):
        loop_counter = 0
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self._estado_bombas_local)
                
                if not self.cliente.is_open:
                    logger.warning("Intentando conectar al PLC Modbus en %s:%s...", self.plc_ip, self.plc_port)
                    self.cliente.open()

                if self.cliente.is_open:
                    loop_counter += 1
                    if loop_counter % 5 == 0:  # Imprimir cada 5 segundos para no saturar la pantalla
                        logger.info("Conectado al PLC. Enviando telemetria y leyendo comandos...")"""
                        
    content = content.replace(old_loop_start, new_loop_start)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

update_daemon('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', False)
update_daemon('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/test_daemon.py', True)
