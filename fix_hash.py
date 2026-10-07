import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/database/db.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('pwd_admin = generate_password_hash("Xy@9!pL2_mQz7$vW")', 'pwd_admin = generate_password_hash("Xy@9!pL2_mQz7$vW", method="pbkdf2:sha256:150000")')

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/database/db.py', 'w', encoding='utf-8') as f:
    f.write(content)
