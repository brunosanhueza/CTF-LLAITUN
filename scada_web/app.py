import os
import time
from functools import wraps
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

from database.db import (
    init_db,
    verificar_credenciales,
    obtener_usuario_por_id,
    obtener_bitacoras,
    guardar_bitacora,
    promover_a_admin,
    buscar_operador
)
from web_scada_client import WebScadaClient

base_dir = os.path.abspath(os.path.dirname(__file__))
upload_folder = os.path.join(base_dir, 'uploads')
os.makedirs(upload_folder, exist_ok=True)

app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, 'templates'),
    static_folder=os.path.join(base_dir, 'static')
)

app.config['SECRET_KEY'] = 'aguas-del-valle-super-secret-key-2026-scada'
app.config['UPLOAD_FOLDER'] = upload_folder
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

init_db()
scada_client = WebScadaClient(socketio)
scada_client.iniciar()  # Added to start the PLC background polling



def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('rol') != 'admin':
            flash("Acceso denegado: Se requieren privilegios de Administrador SCADA.", "error")
            return redirect(url_for('intranet'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
def index():
    if 'user_id' in session:
        if session.get('rol') == 'admin':
            return redirect(url_for('admin_panel'))
        return redirect(url_for('intranet'))
    return redirect(url_for('login'))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = verificar_credenciales(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['nombre'] = user['nombre']
            session['rol'] = user['rol']
            session['avatar_url'] = user.get('avatar_url', '/static/img/default-avatar.png')

            flash(f"Bienvenido/a, {user['nombre']}.", "success")
            if user['rol'] == 'admin':
                return redirect(url_for('admin_panel'))
            return redirect(url_for('intranet'))
        else:
            flash("Credenciales inválidas. Compruebe usuario y contraseña.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Has cerrado sesión exitosamente.", "info")
    return redirect(url_for('login'))


@app.route("/intranet")
@login_required
def intranet():
    bitacoras = obtener_bitacoras()
    return render_template("intranet.html", bitacoras=bitacoras, usuario=session)


@app.route("/intranet/upload", methods=["POST"])
@login_required
def upload_file():
    if 'archivo' not in request.files:
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for('intranet'))

    file = request.files['archivo']
    titulo = request.form.get("titulo", "Reporte de turno").strip()
    descripcion = request.form.get("descripcion", "").strip()

    if file.filename == '':
        flash("El nombre de archivo no puede estar vacío.", "error")
        return redirect(url_for('intranet'))

    if file:
        filename = secure_filename(file.filename)
        if not filename:
            filename = f"reporte_{int(time.time())}.dat"

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        flash(f"Archivo '{filename}' subido y registrado en la bitácora correctamente.", "success")
        guardar_bitacora(session['user_id'], titulo, descripcion, filename)
        return redirect(url_for('intranet'))


@app.route("/intranet/download")
@login_required
def download_file():
    # VULNERABILIDAD INTENCIONAL: LFI (Local File Inclusion) / Path Traversal
    # No sanitizamos la variable 'file', lo que permite inyectar ../ o rutas absolutas.
    filename = request.args.get('file')
    if not filename:
        return redirect(url_for('intranet'))
    
    # La concatenación insegura es el corazón de la vulnerabilidad
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        from flask import send_file
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return f"Error del sistema: Archivo no encontrado o permiso denegado.", 404


@app.route("/admin")
@admin_required
def admin_panel():
    # El "Trofeo de Vuelta": Solo el admin real (o alguien que forzó su hash) verá la Flag.
    # Esta parte de Python es la que quedará cifrada/ofuscada después con PyArmor o Cython.
    part1 = "CtF_L1@I7uN"
    part2 = "{paS5!!_1lAItuN_@GuA}"
    flag_secreta = part1 + part2
    
    return render_template("admin.html", usuario=session, secret_admin_flag=flag_secreta)

@app.route("/api/v1/search")
def api_search():
    """Endpoint público para buscar información básica de operadores. Vulnerable a SQLi."""
    q = request.args.get('query', '')
    resultados = buscar_operador(q) if q else []
    return jsonify(resultados)

@app.route("/internal/messages")
@login_required
def chat_interno():
    """
    Ruta oculta (sin botones en la UI). Se encuentra haciendo Fuzzing con diccionarios comunes.
    Revela la pista crítica para iniciar la Fase 2.
    """
    chats = [
        {"de": "admin_scada", "para": "op_turno1", "fecha": "2026-10-02 14:02", 
         "mensaje": "Oye, el nuevo sistema de diagnóstico ya está instalado en el servidor Debian corporativo."},
        {"de": "op_turno1", "para": "admin_scada", "fecha": "2026-10-02 14:05", 
         "mensaje": "Recibido jefe. ¿Cómo me conecto si la VPN de mantenimiento sigue fallando?"},
        {"de": "admin_scada", "para": "op_turno1", "fecha": "2026-10-02 14:10", 
         "mensaje": "Creé un respaldo de las credenciales de SSH en el archivo /var/backups/credenciales_ot.bak del servidor. Para que los bots no las lean, cifré el contenido del archivo con ROT47. Usa la herramienta de descargas del portal web para bajar el archivo si lo necesitas urgente."}
    ]
    html = """
    <html>
    <head><title>Foro Interno - IT & SCADA</title>
    <style>
        body { background-color: #c0c0c0; color: #000; font-family: "Times New Roman", Times, serif; }
        .post { border: 1px solid #000; margin-bottom: 10px; padding: 5px; background: #e0e0e0; }
        .header { background: #000080; color: #fff; padding: 2px; font-weight: bold; }
    </style>
    </head>
    <body>
    <h1>Foro de Comunicaciones Internas</h1>
    <hr>
    """
    
    for c in chats:
        html += f"""
        <div class="post">
            <div class="header">De: {c['de']} | Para: {c['para']} | Fecha: {c['fecha']}</div>
            <p>{c['mensaje']}</p>
        </div>
        """
    html += "</body></html>"
    
    return html

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/v1/telemetry")
def api_telemetria():
    return jsonify(scada_client.obtener_telemetria()), 200


@app.route("/api/v1/reset", methods=["POST", "GET"])
def api_reset():
    # El web client podra enviar un comando por modbus para reiniciar
    return jsonify({"status": "success", "message": "Comando de reset enviado."}), 200


@socketio.on('connect')
def handle_connect():
    emit('telemetria', scada_client.obtener_telemetria())


@socketio.on('reset_sistema')
def handle_reset_sistema():
    emit('telemetria', scada_client.obtener_telemetria(), broadcast=True)


if __name__ == "__main__":
    scada_client.iniciar()
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
