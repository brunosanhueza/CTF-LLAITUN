import re

file_path = 'c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/test_daemon.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix sensor initialization
old_sensor_init = """                # Agregamos None directamente al primer sensor (Canal 0)
                self.sensores.append(None)
                
                # Inicializamos los otros tres (Estanques 2, 3 y 4) en los canales 1, 2 y 3
                for canal in [1, 2, 3]:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                    except Exception:
                        self.sensores.append(None)"""

new_sensor_init = """                # CODIGO MODIFICADO Y ADAPTADO DESDE C3-PLC: 
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

content = content.replace(old_sensor_init, new_sensor_init)

# 2. Fix Modbus write (implementing multiple registers for both RAW and PCT as per C3-PLC/config.py)
old_modbus_write = """                        # Escribir lecturas (simulamos HR 21,22,23,24, etc, pero aqui solo mandamos distancias para simplificar)
                        # HR 21 (P1)=ch2, HR 23 (P2)=ch0, HR 25 (P3)=ch3, HR 27 (P4)=ch1
                        # Mapeo segun mapa_sensores.py del cuadrante 3
                        self.cliente.write_single_register(21, distancias_suavizadas[2])
                        self.cliente.write_single_register(23, distancias_suavizadas[0])
                        self.cliente.write_single_register(25, distancias_suavizadas[3])
                        self.cliente.write_single_register(27, distancias_suavizadas[1])"""

new_modbus_write = """                        # Escribir lecturas a Modbus (RAW y PCT)
                        # Mapeo actualizado desde C3-PLC/config.py:
                        # Estanque 1 (P1): Canal 2 -> HR 21 (RAW), HR 22 (PCT)
                        # Estanque 2 (P2): Canal 0 -> HR 23 (RAW), HR 24 (PCT)
                        # Estanque 3 (P3): Canal 3 -> HR 25 (RAW), HR 26 (PCT)
                        # Estanque 4 (P4): Canal 1 -> HR 27 (RAW), HR 28 (PCT)
                        
                        pct_p1 = int(self._calcular_pct_local(distancias_suavizadas[2]))
                        pct_p2 = int(self._calcular_pct_local(distancias_suavizadas[0]))
                        pct_p3 = int(self._calcular_pct_local(distancias_suavizadas[3]))
                        pct_p4 = int(self._calcular_pct_local(distancias_suavizadas[1]))
                        
                        registros_sensores = [
                            distancias_suavizadas[2], pct_p1,  # HR 21, 22
                            distancias_suavizadas[0], pct_p2,  # HR 23, 24
                            distancias_suavizadas[3], pct_p3,  # HR 25, 26
                            distancias_suavizadas[1], pct_p4   # HR 27, 28
                        ]
                        
                        self.cliente.write_multiple_registers(21, registros_sensores)"""

content = content.replace(old_modbus_write, new_modbus_write)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
