import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/web_scada_client.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'"rele": \{"estado": False\}\s*\}')

new_block = """"rele": {"estado": False},
            "plc_ip": self.target_ip
        }"""

content_new = pattern.sub(new_block, content)

if content_new != content:
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/web_scada_client.py', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("Success")
else:
    print("Not found")
