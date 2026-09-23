import re

with open("scada_web/templates/dashboard.html", "r", encoding="utf-8") as f:
    html = f.read()

main_match = re.search(r'<main class="scada-dashboard-layout".*?</main>', html, re.DOTALL)
if not main_match:
    main_match = re.search(r'<main.*?</main>', html, re.DOTALL)

minimal_css = """
<style>
    /* iOS 7 Minimalist Flat Design (Maximized & Rectangular) */
    .scada-dashboard-layout {
        display: flex;
        width: 100%;
        min-height: calc(100vh - 80px); /* Adjust based on your top navbar */
        gap: 16px;
        align-items: stretch;
        padding: 0 16px 16px 16px;
        box-sizing: border-box;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .tank-grid {
        flex: 3;
        display: grid;
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr;
        gap: 16px;
        background-color: #000000;
        padding: 16px;
        /* No border radius - Pure rectangular */
    }
    .tank-container {
        background-color: #151516; /* Slightly lighter than pitch black */
        border: 1px solid rgba(255,255,255,0.15);
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
        font-size: 14px;
        font-weight: 500;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 2px;
    }
    .tank-level-text {
        color: #ffffff;
        font-size: 42px;
        font-weight: 200;
        line-height: 1;
    }
    .tank-dist-text {
        color: #ff3b30;
        font-size: 16px;
        font-weight: 400;
        margin-top: 4px;
    }
    .water-fill {
        width: 100%;
        background-color: #0a84ff;
        transition: height 0.3s linear, background-color 0.5s ease;
        position: absolute;
        bottom: 0;
        left: 0;
        opacity: 0.9;
    }
    .water-fill.warning { background-color: #ff9f0a; }
    .water-fill.critical { background-color: #ff453a; opacity: 1; }
    
    .laser-beam {
        position: absolute;
        top: 0;
        left: 80%;
        width: 1px;
        background-color: rgba(255, 59, 48, 0.8);
        transform: translateX(-50%);
        transition: height 0.3s linear;
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
        background-color: rgba(255,255,255,0.2);
    }
    .m-100 { top: 0%; background-color: #ff453a; height: 2px;}
    .m-85 { top: 15%; background-color: #ff9f0a; }
    .m-50 { top: 50%; }
    .m-25 { top: 75%; }
    .marker-text {
        position: absolute;
        right: 45px;
        transform: translateY(-50%);
        font-size: 11px;
        color: #8e8e93;
        font-weight: 400;
    }
    .marker-text-100 { top: 0%; color: #ff453a; font-weight: 600;}
    .marker-text-85 { top: 15%; color: #ff9f0a; }
    .marker-text-50 { top: 50%; }
    .marker-text-25 { top: 75%; }

    .minimal-sidebar {
        flex: 1;
        background-color: #000000;
        padding: 16px;
        color: #ffffff;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    .minimal-card {
        background-color: #151516;
        padding: 20px;
        border: 1px solid rgba(255,255,255,0.15);
        flex: 1;
    }
    .minimal-card h2 {
        font-size: 14px;
        color: #8e8e93;
        text-transform: uppercase;
        font-weight: 500;
        margin: 0 0 16px 0;
        letter-spacing: 0.5px;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        padding-bottom: 8px;
    }
    .minimal-stat {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        font-size: 15px;
    }
    .minimal-stat .value {
        font-weight: 400;
        font-size: 16px;
    }
    .value.green { color: #32d74b; }
    .value.red { color: #ff453a; }
    .value.yellow { color: #ffd60a; }
</style>
"""

tanks_html = ""
for i in range(1, 5):
    tanks_html += f"""
    <div class="tank-container">
        <div class="tank-header">
            <div class="tank-title">ESTANQUE {i}</div>
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
<main class="scada-dashboard-layout">
    {minimal_css}
    <!-- COLUMNA IZQUIERDA: LOS 4 ESTANQUES RECTANGULARES -->
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
            <div style="font-size: 12px; color: #8e8e93; margin-top: 16px;">
                Reset automático configurado en 100% de nivel.
            </div>
        </div>
        
        <div class="minimal-card">
            <h2>Instrumentación PLC</h2>
            <div class="minimal-stat">
                <span>Bomba Principal</span>
                <span id="metric-pump" class="value green">ON</span>
            </div>
            <div class="minimal-stat">
                <span>Relé (GPIO)</span>
                <span id="metric-relay-state" class="value yellow">OFF</span>
            </div>
            <div class="minimal-stat">
                <span>Sensor ToF</span>
                <span id="hardware-badge" class="value">ACTIVO</span>
            </div>
            <div class="minimal-stat" style="font-size: 12px; color: #8e8e93; margin-top: 16px;">
                Target PLC IP: <span id="plc-target-ip" style="color: #ffffff;">10.10.10.4:502</span>
            </div>
        </div>
        
    </div>
</main>
"""

html = html[:main_match.start()] + new_main + html[main_match.end():]

with open("scada_web/templates/dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
