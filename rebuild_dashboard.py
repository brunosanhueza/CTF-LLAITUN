import re

with open("scada_web/templates/dashboard.html", "r", encoding="utf-8") as f:
    html = f.read()

tank_section_match = re.search(r'(<section class="card kiosk-card scada-main-panel">.*?)</section>', html, re.DOTALL)
if tank_section_match:
    tank_svg_code = tank_section_match.group(1)
    
    new_svgs = ""
    for i in range(1, 5):
        svg_i = tank_svg_code
        svg_i = svg_i.replace('id="svg-water-fill"', f'id="svg-water-fill-{i}"')
        svg_i = svg_i.replace('id="laser-beam"', f'id="laser-beam-{i}"')
        svg_i = svg_i.replace('id="pointer-level-text"', f'id="pointer-level-text-{i}"')
        svg_i = svg_i.replace('id="pointer-dist-text"', f'id="pointer-dist-text-{i}"')
        svg_i = svg_i.replace('id="level-guide-line"', f'id="level-guide-line-{i}"')
        svg_i = svg_i.replace('id="level-pointer-badge"', f'id="level-pointer-badge-{i}"')
        svg_i = svg_i.replace('id="overflow-banner"', f'id="overflow-banner-{i}"')
        svg_i = svg_i.replace('id="overflow-spill"', f'id="overflow-spill-{i}"')
        
        # Change title texts
        svg_i = svg_i.replace('>ESTANQUE PRINCIPAL<', f'>ESTANQUE {i}<')
        
        # Modify the section header to not overlap/be too big
        svg_i = svg_i.replace('<section class="card kiosk-card scada-main-panel">', '')
        
        # Adjust dimensions or viewbox if necessary, but we'll use CSS scale
        new_svgs += f'<div class="tank-wrapper" style="position:relative; width:100%; height:100%; transform: scale(0.9); transform-origin: top left;">\n{svg_i}\n</div>'
    
    # Wrap in a grid container
    new_section = f'''
    <section class="card kiosk-card scada-main-panel" style="display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 10px; height: 80vh; padding: 10px;">
        {new_svgs}
    </section>
    '''
    html = html.replace(tank_section_match.group(0), new_section)

# Duplicate the Nivel Estanque card to show all 4 tanks
sidebar_match = re.search(r'(<div class="kiosk-sidebar">.*?</div>)\s*</main>', html, re.DOTALL)
if sidebar_match:
    sidebar = sidebar_match.group(1)
    
    # Replace the single level card with a compact 4-tank level card
    old_card = re.search(r'<!-- CARD 1: NIVEL -->.*?</section>', sidebar, re.DOTALL).group(0)
    
    new_card = '<!-- CARD 1: NIVEL -->\n<section class="card kiosk-card">\n<div class="card-header-actions compact-header">\n<h2>Nivel Estanques</h2>\n</div>\n'
    for i in range(1, 5):
        new_card += f'''
        <div style="margin-bottom: 8px;">
            <div style="display: flex; justify-content: space-between; font-size: 0.9em; margin-bottom: 4px;">
                <span>Tank {i}</span>
                <span><strong id="metric-level-{i}">25.0</strong>% (<span id="metric-dist-{i}">170</span> mm)</span>
            </div>
            <div class="progress-bar-container compact-bar" style="height: 8px;">
                <div id="progress-level-bar-{i}" class="progress-bar" style="width: 25%;"></div>
            </div>
        </div>
        '''
    new_card += '</section>'
    
    sidebar = sidebar.replace(old_card, new_card)
    html = html.replace(sidebar_match.group(1), sidebar)

with open("scada_web/templates/dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
