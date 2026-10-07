import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'    return jsonify\(\{"status": "Confidencial - Log de Comunicaciones", "data": chats\}\)')

new_block = """    html = \"\"\"
    <html>
    <head><title>Foro Interno - IT & SCADA</title>
    <style>
        body { background-color: #c0c0c0; color: #000; font-family: "Times New Roman", Times, serif; }
        .post { border: 1px solid #000; margin-bottom: 10px; padding: 5px; background: #e0e0e0; }
        .header { background: #000080; color: #fff; padding: 2px; font-weight: bold; }
    </style>
    </head>
    <body>
    <h1>Foro de Comunicaciones Internas</h1>
    <hr>
    \"\"\"
    
    for c in chats:
        html += f\"\"\"
        <div class="post">
            <div class="header">De: {c['de']} | Para: {c['para']} | Fecha: {c['fecha']}</div>
            <p>{c['mensaje']}</p>
        </div>
        \"\"\"
    html += "</body></html>"
    
    return html"""

content_new = pattern.sub(new_block, content)

if content_new != content:
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/app.py', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("Success")
else:
    print("Not found")
