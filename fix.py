import sys
import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_bucle = """    def _bucle_control(self):
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self._estado_bombas_local)
                
                if not self.cliente.is_open:
                    self.cliente.open()

                if self.cliente.is_open:
                    # 1. ENVIAR LECTURAS CRUDAS (Con Promedio Movil)
                    distancias_crudas = self.hw.leer_distancias_mm()
                    max_pct_calculado = 0.0
                    bits_alto_sensores = 0

                    if len(distancias_crudas) == 4:
                        distancias_suavizadas = []
                        for i in range(4):
                            dist_cruda = distancias_crudas[i]
                            # Ignorar lecturas de error (8190) para no arruinar el promedio
                            if dist_cruda < 8000:
                                self.historial_distancias[i].append(dist_cruda)
                                if len(self.historial_distancias[i]) > self.max_muestras:
                                    self.historial_distancias[i].pop(0)
                            
                            if len(self.historial_distancias[i]) > 0:
                                promedio = int(sum(self.historial_distancias[i]) / len(self.historial_distancias[i]))
                            else:
                                promedio = 50 # Vacio por defecto
                                
                            distancias_suavizadas.append(promedio)

                            # Calculamos el % solo para ver si alertamos con luces
                            pct = self._calcular_pct_local(promedio)
                            if pct > max_pct_calculado:
                                max_pct_calculado = pct

                            # Control de tiempo en desbordamiento (10s)
                            if pct >= 100.0:
                                self.segundos_desbordados[i] += 1
                            else:
                                self.segundos_desbordados[i] = 0

                            if self.segundos_desbordados[i] >= 10:
                                bits_alto_sensores |= (1 << self.map_alto[i])

                        # HR 21 (P1)=ch2, HR 23 (P2)=ch0, HR 25 (P3)=ch3, HR 27 (P4)=ch1
                        # Mapeo segun mapa_sensores.py del cuadrante 3
                        self.cliente.write_single_register(21, distancias_suavizadas[2])
                        self.cliente.write_single_register(23, distancias_suavizadas[0])
                        self.cliente.write_single_register(25, distancias_suavizadas[3])
                        self.cliente.write_single_register(27, distancias_suavizadas[1])
                        self.cliente.write_single_register(41, 0)
                    else:
                        self.cliente.write_single_register(41, 1)

                    # Watchdog
                    self._contador_watchdog = (self._contador_watchdog + 1) & 0xFFFF
                    self.cliente.write_single_register(40, self._contador_watchdog)

                    # 2. LEER COMANDOS DEL PLC
                    regs_bombas = self.cliente.read_holding_registers(0, 1)
                    regs_color = self.cliente.read_holding_registers(10, 1)

                    if regs_bombas and regs_color:
                        hr_bombas = regs_bombas[0]
                        hr_color = regs_color[0]

                        # --- OVERRIDE DE DESBORDAMIENTO AL PLC ---
                        # Inyectamos Sensor_Nivel_Alto (Bits 8,10,12,14) en HR 0. 
                        # El PLC lo lee y bloquea el bombeo por seguridad.
                        nuevo_hr0 = (hr_bombas & ~0x5500) | bits_alto_sensores
                        if nuevo_hr0 != hr_bombas:
                            self.cliente.write_single_register(0, nuevo_hr0)

                        # Extraemos bits de comando
                        b1 = bool((hr_bombas >> 9) & 1)
                        b2 = bool((hr_bombas >> 11) & 1)
                        b3 = bool((hr_bombas >> 13) & 1)
                        b4 = bool((hr_bombas >> 15) & 1)

                        self.hw.set_bomba(0, b1)
                        self.hw.set_bomba(1, b2)
                        self.hw.set_bomba(2, b3)
                        self.hw.set_bomba(3, b4)
                        
                        self._estado_bombas_local = b1 or b2 or b3 or b4

                        self.hw.set_luminarias(hr_color != 0)
                        
                        # Actualizar luces con el color del PLC o la alerta de nivel
                        self._actualizar_luces(hr_color, max_pct_calculado)

                else:
                    # FAILSAFE: PLC caido o desconectado
                    self.hw.set_bombas(False)
                    self._estado_bombas_local = False
                    self.hw.set_luminarias(False)
                    self.animador_tiras.modo_parpadeo = False
                    self.animador_tiras.color_t1 = (255, 0, 255)
                    self.animador_tiras.color_t2 = (255, 0, 255)

            except Exception as e:
                import traceback
                traceback.print_exc()

            time.sleep(1.0)"""

# Encontramos la definicion de _bucle_control usando expresiones regulares
pattern = re.compile(r'    def _bucle_control\(self\):.*?(?=\n\nclass|\Z)', re.DOTALL)
if pattern.search(content):
    content = pattern.sub(new_bucle, content)
    with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Bucle reemplazado con exito.")
else:
    print("NO SE ENCONTRO BUCLE CONTROL!")
