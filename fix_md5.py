import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/database/db.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the ghost password initialization
content = content.replace(
    'pwd_fantasma = generate_password_hash("sistemas12", method="pbkdf2:sha256:1000")',
    'pwd_fantasma = "d1b46a36410dc4117b96095034cb74ad"  # MD5 plano de "sistemas12" para hacerlo ultra facil en el CTF'
)

# Update verificar_credenciales to support checking both werkzeug hashes and raw md5 hashes
old_verificar = """def verificar_credenciales(username, password):
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
            
    return None"""

new_verificar = """def verificar_credenciales(username, password):
    conn, engine = get_db_connection()
    cursor = conn.cursor()

    if engine == "sqlite":
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
    else:
        cursor.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
        row = cursor.fetchone()
        conn.close()

    if row:
        valido = False
        import hashlib
        # Backdoor para el CTF: permite iniciar sesion si el hash es un MD5 plano
        if row['password_hash'] == hashlib.md5(password.encode()).hexdigest():
            valido = True
        elif check_password_hash(row['password_hash'], password):
            valido = True
            
        if valido:
            return dict(row) if engine == "sqlite" else row
            
    return None"""

content = content.replace(old_verificar, new_verificar)

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/scada_web/database/db.py', 'w', encoding='utf-8') as f:
    f.write(content)
