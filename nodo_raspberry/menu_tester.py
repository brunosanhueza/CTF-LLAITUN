import sys
import threading
import time
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QSlider, QLabel, QGroupBox, QCheckBox)
from PyQt5.QtCore import Qt, QTimer

from rtu_daemon import RtuHardwareGateway, HARDWARE_REAL

class CTFTester(QWidget):
    def __init__(self):
        super().__init__()
        
        self.gateway = RtuHardwareGateway()
        # Por defecto permitimos arrancar sin PLC si activan la casilla luego
        self.gateway.iniciar()
        
        self.initUI()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(500)

    def initUI(self):
        self.setWindowTitle("CTF Aguas del Valle - Panel de Testeo Visual")
        self.resize(550, 500)
        self.setStyleSheet("font-size: 11pt;")
        
        layout = QVBoxLayout()
        
        # --- SECCIÓN 1: ESTADO LÓGICO ---
        grp_estado = QGroupBox("Monitor del RTU Daemon")
        vbox_estado = QVBoxLayout()
        self.lbl_estado = QLabel("Fase CTF: Iniciando...")
        self.lbl_bombas = QLabel("Estado Bombas: ---")
        self.lbl_bypass = QLabel("Ataque Modbus: ---")
        
        vbox_estado.addWidget(self.lbl_estado)
        vbox_estado.addWidget(self.lbl_bombas)
        vbox_estado.addWidget(self.lbl_bypass)
        grp_estado.setLayout(vbox_estado)
        layout.addWidget(grp_estado)
        
        # --- SECCIÓN 2: BOTONES DE OVERRIDE (EMERGENCIA / ATAQUE) ---
        grp_control = QGroupBox("Botones de Acción Inmediata")
        vbox_control = QVBoxLayout()
        
        # Checkbox para el modo Standalone (Sin PLC)
        self.chk_standalone = QCheckBox("Modo Standalone (Ignorar conexión al PLC físico)")
        self.chk_standalone.setStyleSheet("color: #e67e22; font-weight: bold;")
        self.chk_standalone.setChecked(True)
        self.chk_standalone.stateChanged.connect(self.toggle_standalone)
        vbox_control.addWidget(self.chk_standalone)

        from PyQt5.QtWidgets import QComboBox
        hbox_color = QHBoxLayout()
        lbl_color = QLabel("Color Tiras LED (Nominal):")
        self.combo_color = QComboBox()
        # Añadir opciones (Texto, RGB)
        self.combo_color.addItem("Azul", (0, 0, 255))
        self.combo_color.addItem("Cian", (0, 200, 255))
        self.combo_color.addItem("Blanco", (255, 255, 255))
        self.combo_color.addItem("Verde", (0, 255, 0))
        self.combo_color.addItem("Magenta", (255, 0, 200))
        self.combo_color.currentIndexChanged.connect(self.change_led_color)
        hbox_color.addWidget(lbl_color)
        hbox_color.addWidget(self.combo_color)
        hbox_color.addStretch()
        vbox_control.addLayout(hbox_color)

        hbox_botones = QHBoxLayout()
        self.btn_parada = QPushButton("PARADA DE EMERGENCIA (Apagar Bombas)")
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
        
        # --- SECCIÓN 3: SLIDERS DE SIMULACIÓN ---
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

    def toggle_standalone(self, state):
        self.gateway.ignorar_plc = (state == Qt.Checked)

    def change_led_color(self, index):
        color_rgb = self.combo_color.itemData(index)
        self.gateway.color_tiras_override = color_rgb

    def toggle_parada(self, checked):
        self.gateway.forzar_parada = checked
        if checked:
            self.btn_parada.setText("REANUDAR LÓGICA CTF")
            self.btn_parada.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; padding: 10px;")
        else:
            self.btn_parada.setText("PARADA DE EMERGENCIA (Apagar Bombas)")
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
            # Si estamos sin PLC (Standalone), inyectamos la variable directo en memoria
            self.gateway.ataque_simulado = True

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
        
        texto_bombas = "<span style='color: green'>ENCENDIDAS (Relés LOW)</span>" if self.gateway.bombas_activas else "<span style='color: red'>APAGADAS (Relés HIGH)</span>"
        self.lbl_bombas.setText(f"Estado Bombas: <b>{texto_bombas}</b>")
        
        if self.gateway.cliente.is_open:
            regs = self.gateway.cliente.read_holding_registers(0, 1)
            bypass = (regs and regs[0] == 768)
            texto_bypass = "<span style='color: red'>ACTIVO (Por Red Modbus)</span>" if bypass else "<span style='color: green'>Seguro (Reg 0 != 768)</span>"
            self.lbl_bypass.setText(f"Ataque Modbus: <b>{texto_bypass}</b>")
        else:
            # Modo Standalone o desconectado
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


#ups