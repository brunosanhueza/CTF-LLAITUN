with open("scada_web/static/js/dashboard.js", "r", encoding="utf-8") as f:
    js = f.read()

new_js = """
document.addEventListener('DOMContentLoaded', () => {
    const socket = io();

    // DOM Elements - Global
    const systemStateTag = document.getElementById('system-state-tag');
    const hardwareBadge = document.getElementById('hardware-badge');
    const interlockBadge = document.getElementById('interlock-badge');
    const modbusOverrideBadge = document.getElementById('modbus-override-badge');
    const metricPump = document.getElementById('metric-pump');
    const metricServoAngle = document.getElementById('metric-servo-angle');
    const plcTargetIp = document.getElementById('plc-target-ip');
    const btnReset = document.getElementById('btn-reset');
    const screenVignette = document.getElementById('screen-vignette');

    // DOM Elements - Per Tank
    const tanks = [];
    for(let i=1; i<=4; i++) {
        tanks.push({
            id: i,
            svgWaterFill: document.getElementById(`svg-water-fill-${i}`),
            laserBeam: document.getElementById(`laser-beam-${i}`),
            pointerLevelText: document.getElementById(`pointer-level-text-${i}`),
            pointerDistText: document.getElementById(`pointer-dist-text-${i}`),
            levelGuideLine: document.getElementById(`level-guide-line-${i}`),
            levelPointerBadge: document.getElementById(`level-pointer-badge-${i}`),
            overflowBanner: document.getElementById(`overflow-banner-${i}`),
            overflowSpill: document.getElementById(`overflow-spill-${i}`),
            metricLevel: document.getElementById(`metric-level-${i}`),
            metricDist: document.getElementById(`metric-dist-${i}`),
            progressLevelBar: document.getElementById(`progress-level-bar-${i}`)
        });
    }

    const TANK_MAX_HEIGHT_PX = 280;
    const TANK_BOTTOM_Y_PX = 299;
    const TANK_CONTAINER_TOP_Y = 15;

    socket.on('telemetria', (data) => {
        actualizarDashboard(data);
    });

    function actualizarDashboard(data) {
        const bombaActiva = data.bomba_activa;
        const bypassed = data.sensor_bypassed;
        const estado = data.estado;
        const niveles = data.estanques || [0,0,0,0];
        
        // Find max level for global states
        const maxNivel = Math.max(...niveles);

        // Update Tanks
        tanks.forEach((tank, idx) => {
            const nivel = niveles[idx];
            const distMm = 200 - (nivel / 100 * 200); 
            
            if(tank.metricLevel) tank.metricLevel.innerText = nivel.toFixed(1);
            if(tank.progressLevelBar) tank.progressLevelBar.style.width = `${Math.min(100, Math.max(0, nivel))}%`;
            if(tank.metricDist) tank.metricDist.innerText = Math.round(distMm);
            
            if(!tank.svgWaterFill) return; 

            const alturaAguaPx = Math.min(TANK_MAX_HEIGHT_PX, (nivel / 100.0) * TANK_MAX_HEIGHT_PX);
            const yAguaPx = TANK_BOTTOM_Y_PX - alturaAguaPx;
            const yGlobalSuperficie = TANK_CONTAINER_TOP_Y + yAguaPx;

            tank.svgWaterFill.setAttribute('y', yAguaPx);
            tank.svgWaterFill.setAttribute('height', alturaAguaPx);

            if (nivel >= 98.0) {
                tank.svgWaterFill.setAttribute('fill', 'url(#water-grad-critical)');
                if(tank.progressLevelBar) tank.progressLevelBar.style.backgroundColor = '#dc2626';
            } else if (nivel >= 80.0) {
                tank.svgWaterFill.setAttribute('fill', 'url(#water-grad-warning)');
                if(tank.progressLevelBar) tank.progressLevelBar.style.backgroundColor = '#d97706';
            } else {
                tank.svgWaterFill.setAttribute('fill', 'url(#water-grad-normal)');
                if(tank.progressLevelBar) tank.progressLevelBar.style.backgroundColor = '#0284c7';
            }

            if(tank.laserBeam) tank.laserBeam.setAttribute('y2', Math.max(32, yGlobalSuperficie));

            const badgeMaxY = 285; 
            const pointerY = Math.min(badgeMaxY, yGlobalSuperficie);

            if (tank.levelGuideLine) {
                tank.levelGuideLine.setAttribute('y1', yGlobalSuperficie);
                tank.levelGuideLine.setAttribute('y2', pointerY);
            }
            if (tank.levelPointerBadge) {
                tank.levelPointerBadge.setAttribute('transform', `translate(575, ${pointerY})`);
            }
            if (tank.pointerLevelText) tank.pointerLevelText.innerText = `${nivel.toFixed(1)}%`;
            if (tank.pointerDistText) tank.pointerDistText.innerText = `${Math.round(distMm)} mm`;
            
            if(tank.overflowBanner && tank.overflowSpill) {
                if (estado === 'INUNDACION_CRITICA' || nivel >= 98.0) {
                    tank.overflowBanner.classList.remove('hidden');
                    tank.overflowSpill.classList.remove('hidden');
                } else {
                    tank.overflowBanner.classList.add('hidden');
                    tank.overflowSpill.classList.add('hidden');
                }
            }
        });
        
        if (data.plc_ip && plcTargetIp) {
            plcTargetIp.innerText = `${data.plc_ip}:502`;
        }

        if (bombaActiva) {
            if(metricPump) {
                metricPump.innerText = 'ON';
                metricPump.className = 'metric-value text-green';
            }
            if(metricServoAngle) metricServoAngle.innerText = `90° (ABIERTA)`;
        } else {
            if(metricPump) {
                metricPump.innerText = 'OFF';
                metricPump.className = 'metric-value text-red';
            }
            if(metricServoAngle) metricServoAngle.innerText = '0° (CERRADA)';
        }

        if (data.es_hardware) {
            if(hardwareBadge) {
                hardwareBadge.innerText = 'SENSOR FÍSICO I2C';
                hardwareBadge.className = 'badge badge-compact badge-connected';
            }
        } else {
            if(hardwareBadge) {
                hardwareBadge.innerText = 'MODO SIMULACIÓN';
                hardwareBadge.className = 'badge badge-compact badge-neutral';
            }
        }

        const metricRelayState = document.getElementById('metric-relay-state');
        if (metricRelayState && data.rele) {
            if (data.rele.estado) {
                metricRelayState.innerText = 'ON (BOMBEANDO)';
                metricRelayState.className = 'text-green font-bold';
            } else {
                metricRelayState.innerText = 'OFF (REPOSO)';
                metricRelayState.className = 'text-yellow';
            }
        }

        if(interlockBadge && modbusOverrideBadge) {
            if (bypassed) {
                interlockBadge.innerText = 'ANULADO';
                interlockBadge.className = 'state-pill state-danger';
                modbusOverrideBadge.innerText = 'FORZADO';
                modbusOverrideBadge.className = 'state-pill state-danger';
            } else {
                interlockBadge.innerText = 'ENCLAVADO';
                interlockBadge.className = 'state-pill state-normal';
                modbusOverrideBadge.innerText = 'AUTOMÁTICO';
                modbusOverrideBadge.className = 'state-pill state-normal';
            }
        }

        actualizarEstadoGlobal(estado, maxNivel);
        
        if (estado === 'INUNDACION_CRITICA' || maxNivel >= 98.0) {
            if (screenVignette) screenVignette.className = 'vignette-overlay vignette-critical';
        } else {
            if (maxNivel >= 80.0) {
                if (screenVignette) screenVignette.className = 'vignette-overlay vignette-warning';
            } else {
                if (screenVignette) screenVignette.className = 'vignette-overlay';
            }
        }
    }

    function actualizarEstadoGlobal(estado, maxNivel) {
        if(!systemStateTag) return;
        if (estado === 'INUNDACION_CRITICA' || maxNivel >= 98.0) {
            systemStateTag.innerText = 'INUNDACIÓN CRÍTICA';
            systemStateTag.className = 'state-pill state-danger';
        } else if (estado === 'OVERRIDE_ACTIVO') {
            systemStateTag.innerText = 'BYPASS MODBUS ACTIVO';
            systemStateTag.className = 'state-pill state-danger';
        } else if (estado === 'LIMITE_ALCANZADO') {
            systemStateTag.innerText = 'LÍMITE SEGURO (CORTE)';
            systemStateTag.className = 'state-pill state-warning';
        } else if (estado === 'LLENANDO') {
            systemStateTag.innerText = 'LLENANDO ESTANQUE';
            systemStateTag.className = 'state-pill state-normal';
        } else {
            systemStateTag.innerText = 'SISTEMA NOMINAL';
            systemStateTag.className = 'state-pill state-normal';
        }
    }

    if (btnReset) {
        btnReset.addEventListener('click', async () => {
            btnReset.disabled = true;
            try {
                socket.emit('reset_sistema');
                await fetch('/api/reset', { method: 'POST' });
            } catch (err) {
                console.error(err);
            } finally {
                btnReset.disabled = false;
            }
        });
    }
});
"""
with open("scada_web/static/js/dashboard.js", "w", encoding="utf-8") as f:
    f.write(new_js)
