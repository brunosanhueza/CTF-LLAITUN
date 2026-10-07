import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/test_daemon.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_loop = """                for canal in CANALES_SENSORES:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                    except Exception:
                        self.sensores.append(None)"""

new_loop = """                # CODIGO MODIFICADO: EL SENSOR DEL ESTANQUE 1 ESTA MALO Y CUELGA EL I2C. LO SALTAMOS
                # for canal in CANALES_SENSORES:
                #     try:
                #         sensor = VL53L0X(self.mux[canal])
                #         self.sensores.append(sensor)
                #     except Exception:
                #         self.sensores.append(None)
                
                # Agregamos None directamente al primer sensor (Canal 0)
                self.sensores.append(None)
                
                # Inicializamos los otros tres (Estanques 2, 3 y 4) en los canales 1, 2 y 3
                for canal in [1, 2, 3]:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                    except Exception:
                        self.sensores.append(None)"""

content = content.replace(old_loop, new_loop)

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/test_daemon.py', 'w', encoding='utf-8') as f:
    f.write(content)
