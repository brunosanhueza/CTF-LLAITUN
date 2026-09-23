import re

with open("scada_web/templates/dashboard.html", "r", encoding="utf-8") as f:
    html = f.read()

# Fix markers width and translucent background
html = html.replace('.tank-markers {', '.tank-markers {\n            background-color: rgba(0, 0, 0, 0.45);\n            backdrop-filter: blur(4px);\n            width: 50px;')

# Fix the 100% clipping by shifting it down instead of -50% Y
html = html.replace('.marker-text-100 { top: 0%; color: #ff453a; font-weight: 600;}', '.marker-text-100 { top: 0%; color: #ff453a; font-weight: 600; transform: translateY(2px); }')

# Move marker lines left slightly to not overlap the text
html = html.replace('.marker {', '.marker {\n            left: 0;')
html = html.replace('right: 45px;', 'right: 4px;\n            text-align: right;\n            width: 40px;')

with open("scada_web/templates/dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
