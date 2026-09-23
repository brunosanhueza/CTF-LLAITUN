import re

with open("scada_web/static/css/static.css", "r", encoding="utf-8") as f:
    css = f.read()

# Replace Frutiger backgrounds
css = re.sub(r'background:\s*radial-gradient[^;]+;', 'background: #151516;', css)
css = re.sub(r'background:\s*linear-gradient[^;]+;', 'background: #151516;', css)
css = re.sub(r'box-shadow:[^;]+;', 'box-shadow: none;', css)
css = re.sub(r'border-radius:\s*[0-9]+px;', 'border-radius: 4px;', css)

# Fix specific glassmorphism colors
css = css.replace('rgba(255, 255, 255, 0.45)', '#151516')
css = css.replace('rgba(255, 255, 255, 0.65)', 'rgba(255, 255, 255, 0.15)')
css = css.replace('#00a8ff', '#0a84ff')

# Fix text colors for dark mode readability
css = css.replace('color: #032b43', 'color: #ffffff')
css = css.replace('color: #054972', 'color: #8e8e93')
css = css.replace('color: #003366', 'color: #ffffff')
css = css.replace('color: #0b538c', 'color: #8e8e93')

# Background image to black
css = re.sub(r'background-image:[^;]+;', 'background: #000000;', css)
# If it has body styling with specific color:
css = re.sub(r'body\s*{[^}]*}', 'body { background: #000000; color: #ffffff; font-family: -apple-system, sans-serif; margin: 0; padding: 0; }', css)

with open("scada_web/static/css/static.css", "w", encoding="utf-8") as f:
    f.write(css)
