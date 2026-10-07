import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/web_scada_client.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'                else:\s*self\._telemetria\["estado"\] = "ERROR"\s*self\._telemetria\["mensaje"\].*')

new_block = """                else:
                    self._telemetria["estado"] = "ERROR"
                    self._telemetria["mensaje"] = "Sin conexión al PLC Modbus."
                    self._telemetria["estanques"] = [0.0, 0.0, 0.0, 0.0]
                    self._telemetria["bomba_activa"] = False"""

content_new = pattern.sub(new_block, content)

if content_new != content:
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/web_scada_client.py', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("Success")
else:
    print("Not found")
