import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/web_scada_client.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """                regs_estado = self.cliente.read_holding_registers(0, 1)
                regs_niveles = self.cliente.read_holding_registers(21, 4)
                
                if regs_estado is not None and regs_niveles is not None:
                    # Extraer el estado de la bomba del Bit 9 (512)
                    self._telemetria["bomba_activa"] = bool((regs_estado[0] >> 9) & 1)
                    
                    # Calcular el Promedio Mvil para dar efecto de telemetra "En Vivo" sin saltos bruscos
                    for i in range(4):
                        val_crudo = regs_niveles[i] / 10.0
                        self.historial_niveles[i].append(val_crudo)"""

new_block = """                regs_estado = self.cliente.read_holding_registers(0, 1)
                regs_niveles = self.cliente.read_holding_registers(21, 8)
                
                if regs_estado is not None and regs_niveles is not None:
                    # Extraer el estado de la bomba del Bit 9 (512)
                    self._telemetria["bomba_activa"] = bool((regs_estado[0] >> 9) & 1)
                    
                    # El PLC manda [Raw, %, Raw, %, Raw, %, Raw, %] en HR 21 a 28
                    pct_values = [regs_niveles[1], regs_niveles[3], regs_niveles[5], regs_niveles[7]]
                    
                    # Calcular el Promedio Movil para dar efecto de telemetria "En Vivo" sin saltos bruscos
                    for i in range(4):
                        val_crudo = pct_values[i] / 10.0
                        self.historial_niveles[i].append(val_crudo)"""

# Instead of regex, we can just do string replace
if "regs_niveles = self.cliente.read_holding_registers(21, 4)" in content:
    content = content.replace("regs_niveles = self.cliente.read_holding_registers(21, 4)", "regs_niveles = self.cliente.read_holding_registers(21, 8)")
    content = content.replace("val_crudo = regs_niveles[i] / 10.0", "pct_values = [regs_niveles[1], regs_niveles[3], regs_niveles[5], regs_niveles[7]]\n                        val_crudo = pct_values[i] / 10.0")
    
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/web_scada_client.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Success")
else:
    print("Not found")
