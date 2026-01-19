#!/bin/bash
set -e

# Configuración de rutas para el almacén de certificados de NSS (Linux)
NSS_DB="$HOME/.pki/nssdb"
mkdir -p "$NSS_DB"

# Inicializar la base de datos de NSS si no existe
if [ ! -f "$NSS_DB/pkcs11.txt" ]; then
    certutil -N -d sql:"$NSS_DB" --empty-password
fi

# Importar el certificado si se ha proporcionado la ruta y la contraseña
if [ -n "$CERT_PATH" ] && [ -f "$CERT_PATH" ]; then
    echo "Importando certificado desde $CERT_PATH..."
    
    # Usamos pk12util para importar el .p12/.pfx
    # Nota: Si el certificado tiene contraseña, se debe pasar de forma segura
    if [ -n "$CERT_PASSWORD" ]; then
        pk12util -i "$CERT_PATH" -d sql:"$NSS_DB" -W "$CERT_PASSWORD"
    else
        pk12util -i "$CERT_PATH" -d sql:"$NSS_DB" -W ""
    fi
    
    echo "Certificado importado correctamente."
else
    echo "AVISO: No se ha detectado CERT_PATH o el archivo no existe. El bot podría fallar si requiere autenticación."
fi

# Iniciar el worker de Python
echo "Iniciando Xaloc Worker..."
exec python worker.py "$@"
