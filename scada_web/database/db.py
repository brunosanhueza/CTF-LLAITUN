import os
import sqlite3
import logging
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

DB_TYPE = os.environ.get("DB_TYPE", "mysql")
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 3306))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "zacky5023")
MYSQL_DB = os.environ.get("MYSQL_DB", "aguas_del_valle")

SQLITE_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "aguas_del_valle.db")

MYSQL_AVAILABLE = False
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    try:
        import mysql.connector as pymysql
        MYSQL_AVAILABLE = True
    except ImportError:
        MYSQL_AVAILABLE = False


def _crear_base_datos_mysql_si_no_existe():
    if DB_TYPE == "mysql" and MYSQL_AVAILABLE:
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                autocommit=True
            )
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Error verificando base de datos MySQL: {e}")


def get_db_connection():
    if DB_TYPE == "mysql" and MYSQL_AVAILABLE:
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                cursorclass=pymysql.cursors.DictCursor if hasattr(pymysql, 'cursors') else None,
                autocommit=True
            )
            return conn, "mysql"
        except Exception as e:
            logger.warning(f"Error conexion MySQL: {e}")
    
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn, "sqlite"


def init_db():
    _crear_base_datos_mysql_si_no_existe()
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'operador',
                avatar_url TEXT DEFAULT '/static/img/default-avatar.png',
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitacoras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                titulo TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                archivo_adjunto TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                nombre VARCHAR(100) NOT NULL,
                rol VARCHAR(20) NOT NULL DEFAULT 'operador',
                avatar_url VARCHAR(255) DEFAULT '/static/img/default-avatar.png',
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitacoras (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT,
                titulo VARCHAR(150) NOT NULL,
                descripcion TEXT NOT NULL,
                archivo_adjunto VARCHAR(255),
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            );
        """)

    cursor.execute("SELECT COUNT(*) FROM usuarios")
    count = cursor.fetchone()[0] if engine == "sqlite" else cursor.fetchone()['COUNT(*)']

    if count == 0:
        pwd_operador = generate_password_hash("operador2026")
        pwd_admin = generate_password_hash("Adm1n_Pl4nt4_S3cur3!#")

        if engine == "sqlite":
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nombre, rol)
                VALUES (?, ?, ?, ?)
            """, ("operador", pwd_operador, "Carlos Morales (Técnico Operador)", "operador"))

            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nombre, rol)
                VALUES (?, ?, ?, ?)
            """, ("admin_scada", pwd_admin, "Ing. Rodrigo Silva (Jefe de Planta)", "admin"))

            cursor.execute("""
                INSERT INTO bitacoras (usuario_id, titulo, descripcion, archivo_adjunto)
                VALUES (1, 'Mantenimiento preventivo Bomba 1', 'Inspección de actuadores y sensor ToF. Parámetros de seguridad verificados según mapa de memoria del PLC.', 'manual_modbus_rev2.txt')
            """)
        else:
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nombre, rol)
                VALUES (%s, %s, %s, %s)
            """, ("operador", pwd_operador, "Carlos Morales (Técnico Operador)", "operador"))

            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nombre, rol)
                VALUES (%s, %s, %s, %s)
            """, ("admin_scada", pwd_admin, "Ing. Rodrigo Silva (Jefe de Planta)", "admin"))

            cursor.execute("""
                INSERT INTO bitacoras (usuario_id, titulo, descripcion, archivo_adjunto)
                VALUES (1, 'Mantenimiento preventivo Bomba 1', 'Inspección de actuadores y sensor ToF. Parámetros de seguridad verificados según mapa de memoria del PLC.', 'manual_modbus_rev2.txt')
            """)

        conn.commit()

    conn.close()


def verificar_credenciales(username, password):
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        if row and check_password_hash(row['password_hash'], password):
            return dict(row)
    else:
        cursor.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
        row = cursor.fetchone()
        conn.close()
        if row and check_password_hash(row['password_hash'], password):
            return row
            
    return None


def obtener_usuario_por_id(user_id):
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("SELECT id, username, nombre, rol, avatar_url FROM usuarios WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    else:
        cursor.execute("SELECT id, username, nombre, rol, avatar_url FROM usuarios WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row


def obtener_bitacoras():
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("""
            SELECT b.id, b.titulo, b.descripcion, b.archivo_adjunto, b.fecha, u.nombre as autor, u.rol
            FROM bitacoras b
            LEFT JOIN usuarios u ON b.usuario_id = u.id
            ORDER BY b.fecha DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    else:
        cursor.execute("""
            SELECT b.id, b.titulo, b.descripcion, b.archivo_adjunto, b.fecha, u.nombre as autor, u.rol
            FROM bitacoras b
            LEFT JOIN usuarios u ON b.usuario_id = u.id
            ORDER BY b.fecha DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows


def guardar_bitacora(usuario_id, titulo, descripcion, archivo_adjunto=""):
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("""
            INSERT INTO bitacoras (usuario_id, titulo, descripcion, archivo_adjunto)
            VALUES (?, ?, ?, ?)
        """, (usuario_id, titulo, descripcion, archivo_adjunto))
        conn.commit()
    else:
        cursor.execute("""
            INSERT INTO bitacoras (usuario_id, titulo, descripcion, archivo_adjunto)
            VALUES (%s, %s, %s, %s)
        """, (usuario_id, titulo, descripcion, archivo_adjunto))
        conn.commit()

    conn.close()


def promover_a_admin(user_id):
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("UPDATE usuarios SET rol = 'admin' WHERE id = ?", (user_id,))
        conn.commit()
    else:
        cursor.execute("UPDATE usuarios SET rol = 'admin' WHERE id = %s", (user_id,))
        conn.commit()

    conn.close()
