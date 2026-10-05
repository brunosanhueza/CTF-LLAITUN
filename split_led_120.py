import sys
import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Update LED count
content = re.sub(r'self\.n_leds_tira = 100', 'self.n_leds_tira = 120', content)

# Update LED gap logic
old_block = r"""                if len\(self\.canales_ws\) > 0:\s+for i in range\(self\.n_leds_tira\):\s+if i % 25 == 24:\s+ws\.ws2811_led_set\(self\.canales_ws\[0\], i, apagado\)\s+else:\s+ws\.ws2811_led_set\(self\.canales_ws\[0\], i, c1 if i < encendidos else apagado\)"""

new_block = """                if len(self.canales_ws) > 0:
                    for i in range(self.n_leds_tira):
                        # Separadores visuales: Bloques de 30 (25 LEDs encendidos, 5 apagados)
                        if (i % 30) >= 25:
                            ws.ws2811_led_set(self.canales_ws[0], i, apagado)
                        else:
                            ws.ws2811_led_set(self.canales_ws[0], i, c1 if i < encendidos else apagado)"""

content_new = re.sub(old_block, new_block, content)

if content_new != content:
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("Success")
else:
    print("Not found")
