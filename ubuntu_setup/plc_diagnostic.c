#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Herramienta de Diagnóstico PLC - AGUAS DEL VALLE S.A.
// Compilar con: gcc plc_diagnostic.c -o plc_diagnostic -fno-stack-protector -no-pie

void plc_ping(char *ip_address) {
    char buffer[64]; // Búfer vulnerable de tamaño fijo (64 bytes)
    
    // VULNERABILIDAD CRÍTICA: strcpy no verifica el límite del búfer.
    // Si ip_address tiene más de 64 caracteres, desbordará el stack
    // y sobrescribirá el Return Address.
    strcpy(buffer, ip_address);
    
    printf("[+] Verificando conectividad Modbus TCP con PLC...\n");
    printf("[+] Haciendo ping al host: %s\n", buffer);
    printf("[+] Ping exitoso. PLC respondiendo en puerto 502.\n");
}

int main(int argc, char *argv[]) {
    // Al ejecutarse como SUID, seteamos explícitamente el UID y GID a 0 (root)
    // Esto asegura que cuando el hacker llame a system("/bin/sh") en su exploit,
    // la consola conserve los privilegios de root.
    setresuid(0, 0, 0);
    setresgid(0, 0, 0);

    printf("===============================================\n");
    printf(" AGUAS DEL VALLE S.A. - PLC DIAGNOSTIC TOOL v1.2\n");
    printf("===============================================\n");

    if (argc < 2) {
        printf("[!] Error: Parámetro faltante.\n");
        printf("Uso: %s <IP_DEL_PLC>\n", argv[0]);
        exit(1);
    }

    plc_ping(argv[1]);
    
    return 0;
}
