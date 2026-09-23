
document.addEventListener('DOMContentLoaded', () => {
    const socket = io();

    // DOM Elements - Global
    const systemStateTag = document.getElementById('system-state-tag');
    const hardwareBadge = document.getElementById('hardware-badge');
    const interlockBadge = document.getElementById('interlock-badge');
    const metricPump = document.getElementById('metric-pump');
    const plcTargetIp = document.getElementById('plc-target-ip');
    const metricRelayState = document.getElementById('metric-relay-state');

    // DOM Elements - Per Tank
    const tanks = [];
    for(let i=1; i<=4; i++) {
        tanks.push({
            id: i,
            waterFill: document.getElementById(`water-fill-${i}`),
            laserBeam: document.getElementById(`laser-beam-${i}`),
            metricLevel: document.getElementById(`metric-level-${i}`),
            metricDist: document.getElementById(`metric-dist-${i}`)
        });
    }

    socket.on('telemetria', (data) => {
        actualizarDashboard(data);
    });

    function actualizarDashboard(data) {
        const bombaActiva = data.bomba_activa;
        const bypassed = data.sensor_bypassed;
        const estado = data.estado;
        const niveles = data.estanques || [0,0,0,0];
        
        const maxNivel = Math.max(...niveles);

        tanks.forEach((tank, idx) => {
            const nivel = niveles[idx];
            const distMm = 200 - (nivel / 100 * 200); 
            
            if(tank.metricLevel) tank.metricLevel.innerText = nivel.toFixed(1);
            if(tank.metricDist) tank.metricDist.innerText = Math.round(distMm) + " mm";
            
            if(!tank.waterFill) return; 

            // Water height is exactly the percentage
            tank.waterFill.style.height = `${Math.min(100, Math.max(0, nivel))}%`;

            if (nivel >= 98.0) {
                tank.waterFill.className = 'water-fill critical';
            } else if (nivel >= 80.0) {
                tank.waterFill.className = 'water-fill warning';
            } else {
                tank.waterFill.className = 'water-fill';
            }
            
            // Laser beam goes down from 0 to the water surface
            if(tank.laserBeam) {
                tank.laserBeam.style.height = `${100 - Math.min(100, Math.max(0, nivel))}%`;
            }
        });
        
        if (data.plc_ip && plcTargetIp) {
            plcTargetIp.innerText = `${data.plc_ip}:502`;
        }

        if (bombaActiva) {
            if(metricPump) {
                metricPump.innerText = 'ON';
                metricPump.className = 'value green';
            }
        } else {
            if(metricPump) {
                metricPump.innerText = 'OFF';
                metricPump.className = 'value red';
            }
        }

        if (data.es_hardware) {
            if(hardwareBadge) {
                hardwareBadge.innerText = 'ACTIVO (FISICO)';
                hardwareBadge.className = 'value green';
            }
        } else {
            if(hardwareBadge) {
                hardwareBadge.innerText = 'SIMULADO';
                hardwareBadge.className = 'value yellow';
            }
        }

        if (metricRelayState && data.rele) {
            if (data.rele.estado) {
                metricRelayState.innerText = 'ON';
                metricRelayState.className = 'value green';
            } else {
                metricRelayState.innerText = 'OFF';
                metricRelayState.className = 'value yellow';
            }
        }

        if(interlockBadge) {
            if (bypassed) {
                interlockBadge.innerText = 'BYPASSED';
                interlockBadge.className = 'value red';
            } else {
                interlockBadge.innerText = 'ENCLAVADO';
                interlockBadge.className = 'value green';
            }
        }

        actualizarEstadoGlobal(estado, maxNivel);
    }

    function actualizarEstadoGlobal(estado, maxNivel) {
        if(!systemStateTag) return;
        if (estado === 'INUNDACION_CRITICA' || maxNivel >= 98.0) {
            systemStateTag.innerText = 'CRÍTICO / OVERFLOW';
            systemStateTag.className = 'value red';
        } else if (estado === 'OVERRIDE_ACTIVO') {
            systemStateTag.innerText = 'OVERRIDE MODBUS';
            systemStateTag.className = 'value red';
        } else if (estado === 'LIMITE_ALCANZADO') {
            systemStateTag.innerText = 'LÍMITE ALCANZADO';
            systemStateTag.className = 'value yellow';
        } else if (estado === 'LLENANDO') {
            systemStateTag.innerText = 'LLENANDO...';
            systemStateTag.className = 'value green';
        } else {
            systemStateTag.innerText = 'NOMINAL';
            systemStateTag.className = 'value green';
        }
    }
});
