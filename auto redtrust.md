# Integración Automática de Certificados Redtrust

Este documento detalla la estrategia para automatizar la carga de certificados de Redtrust mediante políticas de navegador, y define los puntos clave que **tú debes investigar** para completar la integración.

---

## 🎯 Objetivo
Eliminar el selector de certificados manual y PyAutoGUI, permitiendo que el navegador elija el certificado correcto basándose en el cliente procesado.

---

## 🔍 Funcionamiento de Certificados en este Proyecto

El proyecto usa la política `AutoSelectCertificateForUrls` de Edge. 
1. Se especifica una URL.
2. Se especifica un filtro (ej: `CN` del certificado).
3. El navegador busca en el almacén de Windows el certificado que coincida y lo usa sin preguntar.

**Punto de referencia (`url-cert-config.bat`):**
```batch
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls" /v 1 /t REG_SZ /d "{\"pattern\":\"https://sede.madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"%CN%\"}}}" /f
```

---

## ❓ Dudas a Investigar (Tu Turno)

Para que podamos automatizar esto, necesito que investigues los siguientes puntos sobre cómo se comporta Redtrust en tu entorno:

### 1. Visibilidad en el Sistema
¿Cómo "aparece" el certificado en Windows cuando lo seleccionas en Redtrust?
- **Tarea**: Abre un certificado en Redtrust y ejecuta este comando en PowerShell:
  ```powershell
  Get-ChildItem -Path Cert:\CurrentUser\My | Select-Object Subject, Issuer, Thumbprint, FriendlyName | Format-Table -AutoSize
  ```
- **Pregunta**: ¿Aparece el certificado con un `CN` (Common Name) único que identifique al cliente? ¿El `Issuer` es siempre el mismo para Redtrust o varía por cliente?

### 2. Automatización del Agente
¿Permite el Agente de Redtrust "abrir" o "activar" un certificado programáticamente?
- **Tarea**: Busca en la carpeta de instalación de Redtrust (normalmente en `Program Files`) si hay algún ejecutable con ayuda de línea de comandos (ej: `rtagent.exe --help`, `redtrust-cli.exe`, etc.).
- **Pregunta**: ¿Existe alguna forma de llamar al agente por consola pasando el nombre del cliente o un ID? ¿O existe alguna API local (puerto 8080, etc.) a la que el Agente responda?

### 3. Persistencia de la Sesión
¿Cuánto tiempo se mantiene "abierto" el certificado en el almacén de Windows una vez seleccionado?
- **Pregunta**: Si abres el certificado, ¿se queda ahí hasta que reinicias, hasta que cierras el agente, o tiene un timeout? (Esto es clave para saber si debemos "abrirlo" justo antes de cada trámite).

---

## 🛠️ Cómo se integrará (Una vez aclaradas las dudas)

Si confirmamos que podemos ver el `CN` y/o activar el certificado por consola, el flujo será:

1. **Pre-activación**: Llamar al CLI de Redtrust (si existe) para el cliente X.
2. **Configuración**: El script de Python leerá el `CN` asociado y actualizará el registro:
   ```python
   # Idea de implementación
   def setup_policy(client_cn):
       # Aquí iría el código para borrar y recrear los valores en 
       # HKLM\SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls
       pass
   ```
3. **Ejecución**: Se lanza el worker de Playwright/Edge y el login será instantáneo.

---

## 🧪 Plan para tus Pruebas

1. **Prueba 1**: Abre el certificado de un cliente en Redtrust -> Ejecuta el comando de PowerShell -> Copia el `CN` exacto -> Ponlo manualmente en un comando `reg add` (como el del ejemplo arriba) -> Abre Edge y ve a la web del trámite.
   - **Resultado esperado**: Que no salga el popup de selector de certificados.

2. **Prueba 2**: Cerrar Redtrust o el certificado -> Confirmar que desaparece del almacén con PowerShell.
   - **Resultado esperado**: Ayuda a entender si necesitamos gestión de sesión activa.
