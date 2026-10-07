import re

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    gateway = RtuHardwareGateway()
    try:
        gateway.iniciar()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gateway.detener()"""

new_block = """if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    print("==================================================")
    print("  INICIANDO DAEMON RTU - AGUAS DEL VALLE S.A.  ")
    print("==================================================")
    gateway = RtuHardwareGateway()
    try:
        gateway.iniciar()
        print("[INFO] Daemon iniciado correctamente. Presiona CTRL+C para detener.")
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\\n[INFO] Deteniendo el demonio de hardware...")
        gateway.detener()
        print("[INFO] Apagado completo.")"""

content = content.replace(old_block, new_block)

with open('c:/Users/zacky/Desktop/proyectos/ctf-aguas/nodo_raspberry/rtu_daemon.py', 'w', encoding='utf-8') as f:
    f.write(content)
