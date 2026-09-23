import re

with open("scada_web/templates/dashboard.html", "r", encoding="utf-8") as f:
    html = f.read()

# Replace the whole <main class="scada-dashboard-layout"> block
main_match = re.search(r'<main class="scada-dashboard-layout">.*?</main>', html, re.DOTALL)

minimal_css = """
<style>
    /* iOS 7 Minimalist Design */
    .tank-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        grid-template-rows: repeat(2, 1fr);
        gap: 16px;
        height: 70vh;
        background-color: #000000;
        padding: 16px;
        border-radius: 12px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .tank-container {
        background-color: #1c1c1e;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.1);
        position: relative;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
    }
    .tank-header {
        position: absolute;
        top: 16px;
        left: 20px;
        z-index: 10;
    }
    .tank-title {
        color: #8e8e93;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        margin-bottom: 2px;
    }
    .tank-level-text {
        color: #ffffff;
        font-size: 36px;
        font-weight: 200;
        line-height: 1;
    }
    .tank-dist-text {
        color: #ff3b30;
        font-size: 14px;
        font-weight: 400;
        margin-top: 4px;
    }
    .water-fill {
        width: 100%;
        background-color: #0a84ff;
        transition: height 0.5s cubic-bezier(0.2, 0.8, 0.2, 1), background-color 0.5s ease;
        position: absolute;
        bottom: 0;
        left: 0;
        opacity: 0.85;
    }
    .water-fill.warning { background-color: #ff9f0a; }
    .water-fill.critical { background-color: #ff453a; opacity: 1; }
    
    .laser-beam {
        position: absolute;
        top: 0;
        left: 80%;
        width: 1px;
        background-color: rgba(255, 59, 48, 0.7);
        transform: translateX(-50%);
        transition: height 0.5s ease;
        z-index: 5;
    }
    
    .tank-markers {
        position: absolute;
        right: 0;
        top: 0;
        height: 100%;
        width: 40px;
        border-left: 1px solid rgba(255,255,255,0.05);
        pointer-events: none;
        z-index: 10;
    }
    .marker {
        position: absolute;
        width: 100%;
        height: 1px;
        background-color: rgba(255,255,255,0.15);
    }
    .m-100 { top: 0%; background-color: #ff453a; }
    .m-85 { top: 15%; background-color: #ff9f0a; }
    .m-50 { top: 50%; }
    .m-25 { top: 75%; }
    .marker-text {
        position: absolute;
        right: 45px;
        transform: translateY(-50%);
        font-size: 10px;
        color: #8e8e93;
        font-weight: 400;
    }
    .marker-text-100 { top: 0%; color: #ff453a; }
    .marker-text-85 { top: 15%; color: #ff9f0a; }
    .marker-text-50 { top: 50%; }
    .marker-text-25 { top: 75%; }

    .minimal-sidebar {
        background-color: #000000;
        border-radius: 12px;
        padding: 16px;
        color: #ffffff;
        font-family: -apple-system, sans-serif;
    }
    .minimal-card {
        background-color: #1c1c1e;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .minimal-card h2 {
        font-size: 14px;
        color: #8e8e93;
        text-transform: uppercase;
        font-weight: 500;
        margin: 0 0 12px 0;
        letter-spacing: 0.5px;
    }
    .minimal-stat {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        font-size: 15px;
    }
    .minimal-stat .value {
        font-weight: 400;
        font-size: 16px;
    }
    .value.green { color: #32d74b; }
    .value.red { color: #ff453a; }
    .value.yellow { color: #ffd60a; }
    
    .btn-minimal {
        background-color: #0a84ff;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 12px;
        width: 100%;
        font-size: 15px;
        font-weight: 500;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    .btn-minimal:hover { background-color: #0070e5; }
</style>
"""

tanks_html = ""
for i in range(1, 5):
    tanks_html += f"""
    <div class="tank-container">
        <div class="tank-header">
            <div class="tank-title">Estanque {i}</div>
            <div class="tank-level-text"><span id="metric-level-{i}">25.0</span>%</div>
            <div class="tank-dist-text" id="metric-dist-{i}">170 mm</div>
        </div>
        
        <div class="laser-beam" id="laser-beam-{i}" style="height: 75%;"></div>
        
        <div class="water-fill" id="water-fill-{i}" style="height: 25%;"></div>
        
        <div class="tank-markers">
            <div class="marker m-100"></div>
            <div class="marker-text marker-text-100">100%</div>
            
            <div class="marker m-85"></div>
            <div class="marker-text marker-text-85">85%</div>
            
            <div class="marker m-50"></div>
            <div class="marker-text marker-text-50">50%</div>
            
            <div class="marker m-25"></div>
            <div class="marker-text marker-text-25">25%</div>
        </div>
    </div>
    """

new_main = f"""
<main class="scada-dashboard-layout" style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px; align-items: start;">
    {minimal_css}
    <!-- COLUMNA IZQUIERDA: LOS 4 ESTANQUES MINIMALISTAS -->
    <div class="tank-grid">
        {tanks_html}
    </div>

    <!-- COLUMNA DERECHA: SIDEBAR MINIMALISTA -->
    <div class="minimal-sidebar">
        
        <div class="minimal-card">
            <h2>Niveles Generales</h2>
            <div class="minimal-stat">
                <span>Estado Global</span>
                <span id="system-state-tag" class="value green">NOMINAL</span>
            </div>
            <div class="minimal-stat">
                <span>Modbus Interlock</span>
                <span id="interlock-badge" class="value">ENCLAVADO</span>
            </div>
        </div>
        
        <div class="minimal-card">
            <h2>Instrumentacin PLC</h2>
            <div class="minimal-stat">
                <span>Bomba 1</span>
                <span id="metric-pump" class="value green">ON</span>
            </div>
            <div class="minimal-stat">
                <span>Rel (GPIO)</span>
                <span id="metric-relay-state" class="value yellow">OFF</span>
            </div>
            <div class="minimal-stat">
                <span>Sensor ToF</span>
                <span id="hardware-badge" class="value">ACTIVO</span>
            </div>
            <div class="minimal-stat" style="font-size: 12px; color: #8e8e93; margin-top: 10px;">
                PLC IP: <span id="plc-target-ip">10.10.10.4:502</span>
            </div>
        </div>
        
        <div class="minimal-card" style="background: transparent; border: none; padding: 0;">
            <button id="btn-reset" class="btn-minimal">Restablecer Estanques</button>
        </div>
    </div>
</main>
"""

start_idx = html.find('<main class="kiosk-grid">')
end_idx = html.find('</main>') + len('</main>')

if start_idx != -1 and end_idx != -1:
    html = html[:start_idx] + new_main + html[end_idx:]
    with open("scada_web/templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Success")
else:
    print("Could not find main tags")
