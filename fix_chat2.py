import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the specific message string using regex to bypass any encoding/formatting variations
pattern = re.compile(r'"mensaje": "Cre.*?urgente\."\}')

new_text = '"mensaje": "Por seguridad cambié la contraseña del operador IT en el servidor. Te la dejo codificada en base64 para que no quede en texto plano: Q2lCM1IxQWJ7MFAzUjRET1IyMDI2XzY3fQ=="}'

content_new = pattern.sub(new_text, content)

if content_new != content:
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/app.py', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("Success")
else:
    print("Not found")
