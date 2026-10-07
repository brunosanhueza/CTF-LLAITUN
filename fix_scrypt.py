import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/database/db.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'pwd_operador = generate_password_hash("Op3r@dor_V4ll3_2026!!!", method="pbkdf2:sha256:150000")', 
    'pwd_operador = generate_password_hash("Op3r@dor_V4ll3_2026!!!")'
)

content = content.replace(
    'pwd_admin = generate_password_hash("Xy@9!pL2_mQz7$vW", method="pbkdf2:sha256:150000")', 
    'pwd_admin = generate_password_hash("Xy@9!pL2_mQz7$vW")'
)

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/database/db.py', 'w', encoding='utf-8') as f:
    f.write(content)
