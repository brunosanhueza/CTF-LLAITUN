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
    promover_a_admin
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
            return redirect(url_for('portal'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
def index():
    if 'user_id' in session:
        if session.get('rol') == 'admin':
            return redirect(url_for('admin_panel'))
        return redirect(url_for('portal'))
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
            return redirect(url_for('portal'))
        else:
            flash("Credenciales inválidas. Compruebe usuario y contraseña.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Has cerrado sesión exitosamente.", "info")
    return redirect(url_for('login'))


@app.route("/portal")
@login_required
def portal():
    bitacoras = obtener_bitacoras()
    return render_template("portal.html", bitacoras=bitacoras, usuario=session)


@app.route("/portal/upload", methods=["POST"])
@login_required
def upload_file():
    if 'archivo' not in request.files:
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for('portal'))

    file = request.files['archivo']
    titulo = request.form.get("titulo", "Reporte de turno").strip()
    descripcion = request.form.get("descripcion", "").strip()

    if file.filename == '':
        flash("El nombre de archivo no puede estar vacío.", "error")
        return redirect(url_for('portal'))

    if file:
        filename = secure_filename(file.filename)
        if not filename:
            filename = f"reporte_{int(time.time())}.dat"

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        es_payload_elevacion = False
        try:
            with open(filepath, 'r', errors='ignore') as f:
                contenido = f.read()
                if "ELEVATE_ROLE=admin" in contenido or "ADMIN_OVERRIDE_AUTH" in contenido or "import os" in contenido:
                    es_payload_elevacion = True
        except Exception:
            pass

        if es_payload_elevacion or filename.endswith(".sh") or filename.endswith(".py"):
            promover_a_admin(session['user_id'])
            session['rol'] = 'admin'
            flash("Archivo de mantenimiento procesado. Se han actualizado los privilegios de sesión.", "success")
        else:
            flash(f"Archivo '{filename}' subido y registrado en la bitácora correctamente.", "success")

        guardar_bitacora(session['user_id'], titulo, descripcion, filename)
        return redirect(url_for('portal'))


@app.route("/portal/download")
@login_required
def download_file():
    # VULNERABILIDAD INTENCIONAL: LFI (Local File Inclusion) / Path Traversal
    # No sanitizamos la variable 'file', lo que permite inyectar ../ o rutas absolutas.
    filename = request.args.get('file')
    if not filename:
        return redirect(url_for('portal'))
    
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
    return render_template("admin.html", usuario=session)


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/telemetria")
def api_telemetria():
    return jsonify(scada_client.obtener_telemetria()), 200


@app.route("/api/reset", methods=["POST", "GET"])
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
