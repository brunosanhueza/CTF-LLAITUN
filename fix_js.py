import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/static/js/dashboard.js', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'    function actualizarEstadoGlobal\(estado, maxNivel\) \{\s*if\(!systemStateTag\) return;\s*if \(estado === \'INUNDACION_CRITICA\' \|\| maxNivel >= 98\.0\) \{')

new_block = """    function actualizarEstadoGlobal(estado, maxNivel) {
        if(!systemStateTag) return;
        if (estado === 'ERROR') {
            systemStateTag.innerText = 'OFFLINE / NO LINK';
            systemStateTag.className = 'value neutral';
        } else if (estado === 'INUNDACION_CRITICA' || maxNivel >= 98.0) {"""

content_new = pattern.sub(new_block, content)

if content_new != content:
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/static/js/dashboard.js', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("Success")
else:
    print("Not found")
