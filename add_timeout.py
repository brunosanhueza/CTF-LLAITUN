import re

def update_timeout(file_path, is_test):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if is_test:
        old_block = """                logger.info("Iniciando escaneo de sensores I2C (Modo Test - Bypass Canal 2)...")
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
                            
        new_block = """                logger.info("Iniciando escaneo de sensores I2C con timeout de 10s (Modo Test - Bypass Canal 2)...")
                
                def init_sensor_con_timeout(c):
                    res = [None]
                    exc = [None]
                    def _worker():
                        try:
                            res[0] = VL53L0X(self.mux[c])
                        except Exception as err:
                            exc[0] = err
                    t = threading.Thread(target=_worker)
                    t.daemon = True
                    t.start()
                    t.join(10.0)
                    if t.is_alive():
                        raise TimeoutError("TIMEOUT > 10s (Colgado)")
                    if exc[0]:
                        raise exc[0]
                    return res[0]

                for canal in [0, 1, 2, 3]:
                    if canal == 2:  # Estanque 1 roto
                        self.sensores.append(None)
                        logger.warning(f"[-] Canal {canal} IGNORADO intencionalmente por bypass.")
                    else:
                        try:
                            sensor = init_sensor_con_timeout(canal)
                            self.sensores.append(sensor)
                            logger.info(f"[+] Sensor en Canal {canal} INICIALIZADO correctamente.")
                        except Exception as e:
                            self.sensores.append(None)
                            logger.error(f"[X] FALLO CRITICO: El sensor en Canal {canal} se salto por error o timeout ({e})")"""
    else:
        old_block = """                logger.info("Iniciando escaneo de sensores I2C...")
                for canal in CANALES_SENSORES:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                        logger.info(f"[+] Sensor en Canal {canal} INICIALIZADO correctamente.")
                    except Exception as e:
                        self.sensores.append(None)
                        logger.error(f"[X] FALLO CRITICO: El sensor en Canal {canal} NO RESPONDE via I2C ({e})")"""
                        
        new_block = """                logger.info("Iniciando escaneo de sensores I2C con timeout de 10s...")
                
                def init_sensor_con_timeout(c):
                    res = [None]
                    exc = [None]
                    def _worker():
                        try:
                            res[0] = VL53L0X(self.mux[c])
                        except Exception as err:
                            exc[0] = err
                    t = threading.Thread(target=_worker)
                    t.daemon = True
                    t.start()
                    t.join(10.0)
                    if t.is_alive():
                        raise TimeoutError("TIMEOUT > 10s (Colgado)")
                    if exc[0]:
                        raise exc[0]
                    return res[0]

                for canal in CANALES_SENSORES:
                    try:
                        sensor = init_sensor_con_timeout(canal)
                        self.sensores.append(sensor)
                        logger.info(f"[+] Sensor en Canal {canal} INICIALIZADO correctamente.")
                    except Exception as e:
                        self.sensores.append(None)
                        logger.error(f"[X] FALLO CRITICO: El sensor en Canal {canal} se salto por error o timeout ({e})")"""

    content = content.replace(old_block, new_block)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

update_timeout('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', False)
update_timeout('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/test_daemon.py', True)
