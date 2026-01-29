# Implementación de un modulo que haga de cerebro y gestor de recursos

## Contexto

Para poder poner en producción este proyecto y agregar cada vez mas webs sin tener que reinventar la rueda a cada web tenemos que hacer un modulo que gestione todos los recursos que quiere integrar.

Para ello primero tenemos que decidir, de la base de datos, que recursos podemos o no hacer.

En primer lugar, cada web pertenece a un organismo, por ejemplo en el caso de la site xaloc_girona, los organismos con los que se relaciona responden a Select Organisme from recursos.recursosExp where Organisme like '%XALOC%'
en el caso de las otras webs aun tengo que verlo.
Luego de esos casos hay que filtrar por TExp = 2 o TExp = 3
Luego hay que filtrar de esos por estado = 0
Luego se filtra segun el formato de Expedient sea valido siguiendo un formato tal que este 2025/160585-MUL, es decir like '___/______-MUL'
Luego nos asignamos el recurso vemos si podemos scrapear la web para signar el recurso o si no vemos como recontruir el enlace para que funcione, pensando que funciona con un enlace tal que:

http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/telematicos?_token=goysd7kPEoyHEodqvPzqncqwtUL6K1DN5Jdi8zuK&FAlta=&fecpres=&freal=&TExp=0&Procedim=&Organisme=Xaloc&numclient=&Expedient=&SujetoRecurso=&TRecursosDoc=0&Usuario=0&Estado=-1#

Luego de asignarnos todos los que querramos asignarnos, revisamos la tabla de la base de datos y verificamos que somos nosotros los que lo tienen asignado, mirando que el TExp ahora sea = 1 y que el usuario que lo tiene asignado (UsuarioAsignado) con el nombre de nuestra cuenta.

Ahora ya tenemos todas las tareas que hay que realizar...

Lo que queda es organizar los tasks en el worker segun una cola organizada y llamar al task correcto en funcion de la site



----------------------



Aquí tienes el documento maestro (**Master Design Document**) que consolida toda la arquitectura, lógica de negocio y estructura de datos que hemos definido para el "Cerebro" y el sistema de orquestación.

---

# 🧠 Proyecto: Cerebro de Orquestación y Gestión de Recursos (Xvia)

Este documento describe la arquitectura del nuevo módulo encargado de la detección, reclamación y distribución de tareas desde la base de datos central hacia los workers de automatización.

---

## 1. Visión General de la Arquitectura

El sistema se divide en tres capas independientes para garantizar resiliencia y escalabilidad:

1. **SQL Server (Origen):** Base de datos donde residen los recursos brutos.
2. **The Brain (Orquestador):** El "cerebro" que filtra, valida y reclama recursos.
3. **The Worker (Ejecutor):** El proceso encargado de la navegación web y subida de archivos.

---

## 2. El Modelo de Datos de Configuración

Para evitar "reinventar la rueda" con cada nueva web, utilizamos una tabla de configuración dinámica en la base de datos local (SQLite).

### Tabla: `organismo_config`

Define las reglas de negocio para cada sitio web/organismo.

| Campo | Descripción | Ejemplo |
| --- | --- | --- |
| `site_id` | Identificador único del bot. | `xaloc_girona` |
| `query_organisme` | Filtro `LIKE` para SQL Server. | `%XALOC%` |
| `filtro_texp` | Tipos de expediente válidos (CSV). | `2,3` |
| `regex_expediente` | Validación estricta de formato. | `^.{3}/.{6}-MUL$` |
| `url_template` | Plantilla para reconstruir el enlace. | `http://.../telematicos?Expedient={expediente}` |
| `active` | Interruptor de encendido/apagado. | `1` (Activo) |

---

## 3. Lógica del "Cerebro" (Ciclo de Vida del Recurso)

El Orquestador sigue un flujo estrictamente secuencial para garantizar que no haya colisiones entre bots o humanos:

### A. Descubrimiento y Filtrado

El cerebro consulta recursos en SQL Server que cumplan:

* `Organisme` coincida con la configuración activa.
* `TExp` sea igual a 2 o 3.
* `Estado` sea igual a 0.
* El formato de `Expedient` sea válido según la **Regex** definida.

### B. Reclamación (Atomicidad)

Antes de procesar, el cerebro realiza un "Claim" en SQL Server:

```sql
UPDATE Recursos.RecursosExp 
SET TExp = 1, UsuarioAsignado = 'BOT_USER'
WHERE idRecurso = ? AND Estado = 0 AND TExp IN (2,3)

```

> **Nota de Seguridad:** Solo si `rowcount > 0`, el cerebro procede a encolar la tarea. Esto evita que dos procesos tomen el mismo recurso.

### C. Reconstrucción de Enlace

Se genera una URL directa inyectando el número de expediente en el `url_template`. Esto permite al Worker saltarse menús de búsqueda y navegar directamente al recurso objetivo.

---

## 4. Gestión de Colas (Worker Resilience)

El Worker es "inmortal" porque no depende de la conexión constante a SQL Server, sino de una **cola local de tareas** (`tramite_queue` en SQLite).

* **Aislamiento:** Si el Worker muere, la tarea permanece en `pending`. Al reiniciar, el Worker retoma donde se quedó.
* **Seguimiento:** Cada tarea en la cola guarda el `payload` completo, la `url_directa`, el `status` (pending, completed, failed) y el `screenshot_path` final.

---

## 5. Implementación del Bucle Principal (Main Loop)

El "Cerebro" debe ejecutarse como un servicio persistente siguiendo este pseudocódigo:

```python
while True:
    # 1. Leer configuraciones activas (SQLite)
    configs = get_active_configs()
    
    for conf in configs:
        # 2. Buscar candidatos (SQL Server)
        recursos = fetch_remote_resources(conf)
        
        for r in recursos:
            # 3. Intentar reclamar en origen
            if claim_resource_on_remote(r.id):
                # 4. Generar URL y Encolar localmente
                direct_url = build_url(conf.template, r.expediente)
                enqueue_locally(conf.site_id, r.payload, direct_url)
    
    # 5. Dormir para no saturar las bases de datos
    wait(300) 

```

---

## 6. Ventajas del Sistema Definido

* **Modularidad:** Añadir un nuevo organismo (ej. 'Madrid') es solo un `INSERT` en la tabla de configuración.
* **Velocidad:** El Worker ahorra tiempo de navegación gracias a la `url_directa`.
* **Auditabilidad:** Todo el historial de asignación queda registrado en SQL Server (`UsuarioAsignado`) y el historial de ejecución en SQLite.

---

### ¿Cómo proceder?

¿Te gustaría que te ayude a crear un script de **Dashboard básico** para ver el estado de esta tabla `organismo_config` y de la cola de tareas en tiempo real?