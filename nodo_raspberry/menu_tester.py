import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QSlider, QLabel, QGroupBox, QCheckBox, QComboBox)
from PyQt5.QtCore import Qt, QTimer

from rtu_daemon import RtuHardwareGateway, HARDWARE_REAL

class CTFTester(QWidget):
    def __init__(self):
        super().__init__()
        
        self.gateway = RtuHardwareGateway()
        self.gateway.iniciar()
        
        self.initUI()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(500)

    def initUI(self):
        self.setWindowTitle("CTF Aguas del Valle - Panel de Testeo Visual")
        self.resize(600, 700)
        self.setStyleSheet("font-size: 11pt;")
        
        layout = QVBoxLayout()
        
        # --- SECCIÓN 1: ESTADO LÓGICO ---
        grp_estado = QGroupBox("Monitor del RTU Daemon")
        vbox_estado = QVBoxLayout()
        self.lbl_estado = QLabel("Fase CTF: Iniciando...")
        self.lbl_bombas = QLabel("Estado Bombas (Lógica General): ---")
        self.lbl_bypass = QLabel("Ataque Modbus: ---")
        
        vbox_estado.addWidget(self.lbl_estado)
        vbox_estado.addWidget(self.lbl_bombas)
        vbox_estado.addWidget(self.lbl_bypass)
        grp_estado.setLayout(vbox_estado)
        layout.addWidget(grp_estado)
        
        # --- SECCIÓN 2: BOTONES DE OVERRIDE (EMERGENCIA / ATAQUE) ---
        grp_control = QGroupBox("Botones de Acción Global")
        vbox_control = QVBoxLayout()
        
        self.chk_standalone = QCheckBox("Modo Standalone (Ignorar conexión al PLC físico)")
        self.chk_standalone.setStyleSheet("color: #e67e22; font-weight: bold;")
        self.chk_standalone.setChecked(True)
        self.chk_standalone.stateChanged.connect(self.toggle_standalone)
        vbox_control.addWidget(self.chk_standalone)

        hbox_botones = QHBoxLayout()
        self.btn_parada = QPushButton("PARADA DE EMERGENCIA (Apagar Todo)")
        self.btn_parada.setStyleSheet("background-color: #B3261E; color: white; font-weight: bold; padding: 10px;")
        self.btn_parada.setCheckable(True)
        self.btn_parada.clicked.connect(self.toggle_parada)
        hbox_botones.addWidget(self.btn_parada)
        
        self.btn_luminarias = QPushButton("Luminarias: APAGADAS")
        self.btn_luminarias.setCheckable(True)
        self.btn_luminarias.setStyleSheet("background-color: #34495e; color: white; padding: 10px;")
        self.btn_luminarias.clicked.connect(self.toggle_luminarias)
        hbox_botones.addWidget(self.btn_luminarias)
        
        self.btn_ataque = QPushButton("Testear Ataque Modbus\n(Forzar Reg 0 a 768)")
        self.btn_ataque.setStyleSheet("background-color: #F39C12; color: white; font-weight: bold;")
        self.btn_ataque.clicked.connect(self.simular_ataque)
        hbox_botones.addWidget(self.btn_ataque)
        
        vbox_control.addLayout(hbox_botones)
        grp_control.setLayout(vbox_control)
        layout.addWidget(grp_control)
        
        # --- SECCIÓN 3: CONTROL MANUAL DE BOMBAS ---
        grp_bombas = QGroupBox("Control Manual de Relés (Bombas)")
        vbox_bombas = QVBoxLayout()
        
        self.chk_manual_bombas = QCheckBox("Habilitar control individual (Anula el CTF automático)")
        self.chk_manual_bombas.setStyleSheet("font-weight: bold;")
        self.chk_manual_bombas.stateChanged.connect(self.toggle_manual_bombas)
        vbox_bombas.addWidget(self.chk_manual_bombas)
        
        hbox_pumps = QHBoxLayout()
        self.btn_bombas = []
        for i in range(4):
            btn = QPushButton(f"Bomba {i+1} [OFF]")
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, idx=i: self.toggle_bomba(idx, checked))
            hbox_pumps.addWidget(btn)
            self.btn_bombas.append(btn)
        
        vbox_bombas.addLayout(hbox_pumps)
        grp_bombas.setLayout(vbox_bombas)
        layout.addWidget(grp_bombas)
        
        # --- SECCIÓN 4: CONTROL DE COLORES (TIRAS LED) ---
        grp_colores = QGroupBox("Personalización Tiras LED (SK6812 / WS2812B)")
        hbox_colores = QHBoxLayout()
        
        lbl_t1 = QLabel("Tira 1 (Agua/CTF):")
        self.combo_t1 = QComboBox()
        self._fill_color_combo(self.combo_t1)
        self.combo_t1.setCurrentIndex(0) # Azul
        self.combo_t1.currentIndexChanged.connect(self.change_led_color)
        
        lbl_t2 = QLabel("Tira 2 (Edificios):")
        self.combo_t2 = QComboBox()
        self._fill_color_combo(self.combo_t2)
        self.combo_t2.setCurrentIndex(2) # Blanco
        self.combo_t2.currentIndexChanged.connect(self.change_led_color)
        
        hbox_colores.addWidget(lbl_t1)
        hbox_colores.addWidget(self.combo_t1)
        hbox_colores.addWidget(lbl_t2)
        hbox_colores.addWidget(self.combo_t2)
        grp_colores.setLayout(hbox_colores)
        layout.addWidget(grp_colores)
        
        # --- SECCIÓN 5: SLIDERS DE SIMULACIÓN ---
        grp_niveles = QGroupBox("Forzar Niveles (Funciona con o sin Hardware Real)")
        vbox_niveles = QVBoxLayout()
        
        self.chk_override = QCheckBox("Ignorar I2C/Auto-llenado y forzar nivel manual con los sliders")
        self.chk_override.stateChanged.connect(self.toggle_override)
        vbox_niveles.addWidget(self.chk_override)
        
        self.sliders = []
        self.lbl_sliders = []
        for i in range(4):
            hbox = QHBoxLayout()
            lbl = QLabel(f"Estanque {i+1}: 25.0%")
            lbl.setFixedWidth(140)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(25)
            sl.setEnabled(False)
            sl.valueChanged.connect(self.update_sliders)
            
            hbox.addWidget(lbl)
            hbox.addWidget(sl)
            vbox_niveles.addLayout(hbox)
            
            self.sliders.append(sl)
            self.lbl_sliders.append(lbl)
            
        grp_niveles.setLayout(vbox_niveles)
        layout.addWidget(grp_niveles)
        
        self.setLayout(layout)
        self.change_led_color() # Aplicar colores iniciales

    def _fill_color_combo(self, combo):
        combo.addItem("Azul", (0, 0, 255))
        combo.addItem("Cian", (0, 200, 255))
        combo.addItem("Blanco", (255, 255, 255))
        combo.addItem("Verde", (0, 255, 0))
        combo.addItem("Amarillo", (255, 140, 0))
        combo.addItem("Rojo", (255, 0, 0))
        combo.addItem("Magenta", (255, 0, 200))

    def toggle_standalone(self, state):
        self.gateway.ignorar_plc = (state == Qt.Checked)

    def toggle_parada(self, checked):
        self.gateway.forzar_parada = checked
        if checked:
            self.btn_parada.setText("REANUDAR LÓGICA CTF")
            self.btn_parada.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; padding: 10px;")
        else:
            self.btn_parada.setText("PARADA DE EMERGENCIA (Apagar Todo)")
            self.btn_parada.setStyleSheet("background-color: #B3261E; color: white; font-weight: bold; padding: 10px;")

    def toggle_luminarias(self, checked):
        self.gateway.hw.set_luminarias(checked)
        if checked:
            self.btn_luminarias.setText("Luminarias: ENCENDIDAS")
            self.btn_luminarias.setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold; padding: 10px;")
        else:
            self.btn_luminarias.setText("Luminarias: APAGADAS")
            self.btn_luminarias.setStyleSheet("background-color: #34495e; color: white; padding: 10px;")

    def simular_ataque(self):
        if self.gateway.cliente.is_open:
            self.gateway.cliente.write_single_register(0, 768)
        else:
            self.gateway.ataque_simulado = True

    def toggle_manual_bombas(self, state):
        activo = (state == Qt.Checked)
        self.gateway.hw.modo_manual_bombas = activo
        for btn in self.btn_bombas:
            btn.setEnabled(activo)
        # Sincronizar el estado actual al hardware
        if activo:
            for i, btn in enumerate(self.btn_bombas):
                self.gateway.hw.set_bomba(i, btn.isChecked())

    def toggle_bomba(self, idx, checked):
        self.gateway.hw.set_bomba(idx, checked)
        btn = self.btn_bombas[idx]
        if checked:
            btn.setText(f"Bomba {idx+1} [ON]")
            btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold;")
        else:
            btn.setText(f"Bomba {idx+1} [OFF]")
            btn.setStyleSheet("")

    def change_led_color(self):
        c1 = self.combo_t1.itemData(self.combo_t1.currentIndex())
        c2 = self.combo_t2.itemData(self.combo_t2.currentIndex())
        self.gateway.color_tira1_override = c1
        self.gateway.color_tira2_override = c2

    def toggle_override(self, state):
        for sl in self.sliders:
            sl.setEnabled(state == Qt.Checked)
        
        if state == Qt.Checked:
            self.update_sliders()
        else:
            self.gateway.hw.override_niveles = None

    def update_sliders(self):
        if self.chk_override.isChecked():
            niveles = [sl.value() for sl in self.sliders]
            for i, sl in enumerate(self.sliders):
                self.lbl_sliders[i].setText(f"Estanque {i+1}: {sl.value()}.0%")
            self.gateway.hw.override_niveles = niveles

    def update_status(self):
        self.lbl_estado.setText(f"Fase CTF: <b style='color: #2980b9'>{self.gateway.estado}</b>")
        
        texto_bombas = "<span style='color: green'>ENCENDIDAS</span>" if self.gateway.bombas_activas else "<span style='color: red'>APAGADAS</span>"
        self.lbl_bombas.setText(f"Lógica General del CTF para Bombas: <b>{texto_bombas}</b>")
        
        if self.gateway.cliente.is_open:
            regs = self.gateway.cliente.read_holding_registers(0, 1)
            bypass = (regs and regs[0] == 768)
            texto_bypass = "<span style='color: red'>ACTIVO (Por Red Modbus)</span>" if bypass else "<span style='color: green'>Seguro (Reg 0 != 768)</span>"
            self.lbl_bypass.setText(f"Ataque Modbus: <b>{texto_bypass}</b>")
        else:
            if getattr(self.gateway, 'ignorar_plc', False):
                bypass = getattr(self.gateway, 'ataque_simulado', False)
                texto_bypass = "<span style='color: red'>ACTIVO (Ataque Local Simulado)</span>" if bypass else "<span style='color: green'>Seguro (Simulado)</span>"
                self.lbl_bypass.setText(f"Ataque Modbus: <b>{texto_bypass}</b> <span style='color: orange'>[STANDALONE]</span>")
            else:
                self.lbl_bypass.setText("Ataque Modbus: <b style='color: red'>Sin conexión al PLC (Bloqueado)</b>")
        
        if not self.chk_override.isChecked():
            niveles_reales = self.gateway.hw.leer_niveles_pct()
            for i, val in enumerate(niveles_reales):
                self.lbl_sliders[i].setText(f"Estanque {i+1}: {val:.1f}%")

    def closeEvent(self, event):
        self.gateway.detener()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    tester = CTFTester()
    tester.show()
    sys.exit(app.exec_())