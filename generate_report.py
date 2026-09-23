import docx
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

def create_report():
    doc = docx.Document()

    # Title
    title = doc.add_heading('Informe Técnico CTF: SCADA Aguas del Valle', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Intro
    doc.add_heading('1. Resumen Ejecutivo', level=1)
    doc.add_paragraph(
        "El presente documento detalla la arquitectura, endpoints y configuraciones técnicas del desafío "
        "CTF (Capture The Flag) orientado a infraestructuras críticas (OT/ICS). El sistema se ha particionado en "
        "dos entornos aislados para maximizar la seguridad operativa y la inmersión técnica del atacante."
    )

    # Architecture
    doc.add_heading('2. Arquitectura del Sistema', level=1)
    doc.add_paragraph(
        "El ecosistema CTF se ha estructurado en tres componentes físicos y lógicos para emular un entorno OT realista. "
        "El objetivo de los atacantes es comprometer la lógica de seguridad escribiendo en la memoria del PLC."
    )
    
    p = doc.add_paragraph()
    p.add_run("1. PLC Industrial Físico (Target CTF):\n").bold = True
    p.add_run(
        "   Es el equipo real que levanta el puerto 502 (Modbus TCP Server). Actúa como el banco de memoria del sistema y es el vector "
        "de ataque directo. Contiene los registros de telemetría, el flag del CTF y el registro vulnerable de Override."
    )

    p2 = doc.add_paragraph()
    p2.add_run("2. Nodo Físico de Control Edge (nodo_raspberry):\n").bold = True
    p2.add_run(
        "   Una Raspberry Pi que actúa como cliente Modbus y controlador autónomo. Gestiona los sensores de nivel (ToF VL53L0X vía I2C) y "
        "los relés de la bomba. Se encarga de enviar (escribir) la telemetría al PLC Físico y de leer las órdenes (Bypass). "
        "Contiene la inteligencia para cortar el agua al 85% de manera autónoma, a menos que se le ordene lo contrario."
    )
    
    p3 = doc.add_paragraph()
    p3.add_run("3. Servidor HMI SCADA Web (scada_web):\n").bold = True
    p3.add_run(
        "   Máquina Virtual Ubuntu corriendo Docker. Es la interfaz gráfica para visualizar los niveles de agua. Se conecta "
        "como cliente de solo lectura al PLC Físico."
    )

    # Endpoints
    doc.add_heading('3. Endpoints Web y API (scada_web)', level=1)
    doc.add_paragraph("A continuación se detallan las rutas disponibles en la aplicación web (Puerto 5000):")

    table = doc.add_table(rows=1, cols=3)
    table.style = 'Table Grid'
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Ruta (Endpoint)'
    hdr_cells[1].text = 'Método'
    hdr_cells[2].text = 'Descripción'

    endpoints = [
        ("/", "GET", "Redirección a la página de login."),
        ("/login", "GET, POST", "Autenticación de operadores y administradores."),
        ("/logout", "GET", "Cierre de sesión de usuario."),
        ("/portal", "GET", "Panel de control del operador autenticado."),
        ("/portal/upload", "POST", "Vulnerabilidad de carga de archivos arbitrarios (Vector Web)."),
        ("/admin", "GET", "Panel de administración (requiere rol admin). Muestra estado OT."),
        ("/dashboard", "GET", "Vista principal HMI Kiosk (Esquema de los 4 estanques)."),
        ("/api/telemetria", "GET", "Devuelve estado JSON crudo desde Modbus (Socket.IO poll)."),
        ("/api/reset", "GET, POST", "Fuerza reseteo manual simulado desde la web.")
    ]

    for ruta, metodo, desc in endpoints:
        row_cells = table.add_row().cells
        row_cells[0].text = ruta
        row_cells[1].text = metodo
        row_cells[2].text = desc

    doc.add_paragraph("")
    doc.add_heading('3.1 Eventos WebSockets (Socket.IO)', level=2)
    doc.add_paragraph(
        "- telemetria (Servidor -> Cliente): Broadcast emitido cada 1 segundo con los niveles de agua y estado Modbus.\n"
        "- reset_sistema (Cliente -> Servidor): Petición de purga forzada del sistema HMI."
    )

    # Modbus Map
    doc.add_heading('4. Mapa de Memoria Modbus TCP (En el PLC Físico)', level=1)
    doc.add_paragraph(
        "El PLC real aloja los siguientes Holding Registers (Registros de Retención) en el puerto 502:"
    )

    table_modbus = doc.add_table(rows=1, cols=3)
    table_modbus.style = 'Table Grid'
    hdr_cells2 = table_modbus.rows[0].cells
    hdr_cells2[0].text = 'Registro (Offset)'
    hdr_cells2[1].text = 'Acceso (Hacker / Raspi)'
    hdr_cells2[2].text = 'Descripción / Valor'

    modbus_regs = [
        ("0", "Lectura / Escritura", "Registro de Control/Override. Si el atacante escribe 768 (0x0300), la Raspi anula su seguridad del 85%."),
        ("1..16", "Lectura", "Almacena la Flag CTF en texto plano codificado en pares ASCII (CTF{0v3rfl0w_m0dbus_sc4d4_pwn3d})."),
        ("17..20", "Escritura (Solo Raspi)", "Niveles de agua de los 4 estanques (17=Estanque 1, 20=Estanque 4). La Raspi los actualiza multiplicados por 10."),
        ("21", "Escritura (Solo Raspi)", "Estado físico de los relés de la bomba (1 = Encendida, 0 = Apagada).")
    ]

    for reg, acc, desc in modbus_regs:
        row_cells2 = table_modbus.add_row().cells
        row_cells2[0].text = reg
        row_cells2[1].text = acc
        row_cells2[2].text = desc

    doc.add_paragraph("")
    doc.add_heading('5. Lógica de Restablecimiento Automático (Lado Raspberry Pi)', level=1)
    doc.add_paragraph(
        "Para garantizar la usabilidad continua del desafío, la Raspberry Pi se autogestiona frente a ataques exitosos. "
        "Si un atacante inyecta el valor 768 en el Registro 0 del PLC, la Raspberry Pi desactiva su corte de seguridad (85%) y los relés continúan inyectando agua."
    )
    doc.add_paragraph(
        "Al sobrepasar el 100% (Inundación Crítica), la Raspberry Pi inicia un temporizador de 10 segundos para dar tiempo "
        "al atacante de capturar la bandera visual. Transcurrido ese tiempo, la Raspberry Pi actúa como contramedida: se conecta al PLC, sobrescribe el Registro 0 con un '0' para anular el Bypass, y devuelve los estanques a niveles nominales para el siguiente jugador."
    )

    doc.save("DOCUMENTACION_CTF_AGUAS_DEL_VALLE.docx")

if __name__ == "__main__":
    create_report()
