import re

file_path = 'c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/test_daemon.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Make sure we use exact strings or a regex
old_modbus_write = r"                        self\.cliente\.write_single_register\(21, distancias_suavizadas\[2\]\)\s+self\.cliente\.write_single_register\(23, distancias_suavizadas\[0\]\)\s+self\.cliente\.write_single_register\(25, distancias_suavizadas\[3\]\)\s+self\.cliente\.write_single_register\(27, distancias_suavizadas\[1\]\)"

new_modbus_write = """                        # Escribir lecturas a Modbus (RAW y PCT contiguos en un solo request, tal como exige C3-PLC)
                        pct_p1 = int(self._calcular_pct_local(distancias_suavizadas[2]))
                        pct_p2 = int(self._calcular_pct_local(distancias_suavizadas[0]))
                        pct_p3 = int(self._calcular_pct_local(distancias_suavizadas[3]))
                        pct_p4 = int(self._calcular_pct_local(distancias_suavizadas[1]))
                        
                        registros_sensores = [
                            distancias_suavizadas[2], pct_p1,  # HR 21 (RAW), HR 22 (PCT)
                            distancias_suavizadas[0], pct_p2,  # HR 23 (RAW), HR 24 (PCT)
                            distancias_suavizadas[3], pct_p3,  # HR 25 (RAW), HR 26 (PCT)
                            distancias_suavizadas[1], pct_p4   # HR 27 (RAW), HR 28 (PCT)
                        ]
                        self.cliente.write_multiple_registers(21, registros_sensores)"""

content = re.sub(old_modbus_write, new_modbus_write, content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
