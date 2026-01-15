# Análisis de Automatización: Xaloc Girona (Sede Electrónica)

Este documento detalla el análisis técnico realizado sobre el portal de trámites de Xaloc para su automatización mediante Playwright u otras herramientas de testing.

---

## FASE 1: Reconocimiento General

### 1.1 Información Básica

| Aspecto | Qué documentar | Xaloc (Girona) |
|:--------|:---------------|:---------------|
| **URL Base** | Dirección principal | `https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11` |
| **Nombre del trámite** | Título del procedimiento | TRAMITACIÓ EN LÍNIA |
| **Requiere autenticación** | Método de acceso | Sí (Certificado Digital / Cl@ve / VÀLid) |
| **Framework detectado** | Arquitectura base | Joomla! (CMS) + Bootstrap 5.3.8 |
| **Sistema de componentes** | Librería UI usada | STA (Sistema de Tramitació Administrativa) |

### 1.2 Notas de Detección

- **Arquitectura de Información:** El portal principal utiliza Joomla! 5. No es una aplicación Single Page Application (SPA).
- **Entorno de Tramitación:** Una vez iniciada la sesión, la navegación salta al subdominio `seu.xalocgirona.cat`, el cual ejecuta el software STA, identificable por el uso de prefijos `DinVar` en sus campos.
- **UI/UX:** Utiliza componentes de Bootstrap 5 y un editor enriquecido TinyMCE para las áreas de texto largo.

---

## FASE 2: Mapeo del Flujo

### 2.1 Identificación de Pasos

| Paso | Nombre | URL o indicador | Elementos clave | Notas |
|:----:|:-------|:----------------|:----------------|:------|
| 0 | Iniciar Trámite | `.../seu-electronica?view=tramits&id=11` | Botón "Tramitació en línia" | Entrada desde el CMS |
| 1 | Selección de ID | `valid.aoc.cat/o/oauth2/auth...` | Botón `#btnContinuaCert` | Pasarela VÀLid (AOC) |
| 2 | Pasarela de Firma | `cert.valid.aoc.cat/...` | Popup de Certificados | Popup OS: Requiere pulsar "OK" |
| 3 | Formulario Datos | `seu.xalocgirona.cat/sta/Relec/...` | IDs: `contact21`, `DinVar...` | Carga de la App STA |
| 4 | Adjuntar Doc. | Modal de subida | `input#fichero` | Gestión de pruebas físicas |
| 5 | Confirmación | `.../TramitaNoCertForm` | `#lopdok` + Botón Continuar | Final de la Fase 1/3 |

---

## FASE 3: Análisis de Autenticación

### 3.1 Características del OAuth2

El sistema delega la autenticación a la plataforma **VÀLid** de la AOC.

- **Dinamicidad:** La URL de autenticación contiene parámetros `state` y `code` que caducan y cambian en cada sesión. El bot debe iniciar siempre el flujo desde el Paso 0.
- **Interacción Crítica:** Al seleccionar el certificado digital, el navegador abre un diálogo nativo del sistema operativo.
- **Acción:** El bot o el entorno de ejecución debe confirmar la identidad pulsando el botón azul de "OK".
- **Estrategia Playwright:** Se recomienda usar un `browser_context` con un perfil persistente donde el certificado ya esté pre-seleccionado o configurar el navegador para omitir el diálogo de selección.

---

## FASE 4: Análisis de Formularios (Sistema STA)

### 4.1 Campos de Entrada (Inputs)

| Campo | Selector ID | Tipo / Clase | Notas |
|:------|:------------|:-------------|:------|
| Email | `input#contact21` | `.inputObligatorio` | Correo de notificación |
| Nº Denuncia | `input#DinVarNUMDEN` | `.inputObligatorio` | Identificador de la multa |
| Matrícula | `input#DinVarMATRICULA` | `.inputObligatorio` | Placa del vehículo |
| Nº Expediente | `input#DinVarNUMEXP` | `.inputObligatorio` | Referencia del caso |
| Motivos | `body#tinymce` | Rich Text Editor | Dentro de un iframe |

> [!IMPORTANT]
> **Interacción con Motivos (TinyMCE):**
> Al ser un iframe, Playwright debe entrar en el contexto del frame antes de escribir:
> ```python
> await page.frame_locator('#DinVarMOTIUS_ifr').locator('body#tinymce').fill('Texto...')
> ```

---

## FASE 5: Análisis de Subida de Archivos

### 5.1 Lógica de "Adjuntar i Signar"

El sistema no utiliza un input visible de entrada, sino un cargador dinámico.

| Elemento | Selector | Descripción |
|:---------|:---------|:------------|
| **Activador** | `a.docs` con texto "Adjuntar i signar" | Ejecuta `javascript:openUploader(...)` |
| **Input de Archivo** | `input#fichero` | `type="file"` dentro del modal |
| **Confirmación** | Cambio de `<span class="pendiente">` | Estado cambia tras `stepAfterSelect(this)` |

---

## FASE 6: Botones de Navegación y Confirmación

### 6.1 Finalización de Fase

Para poder avanzar, el sistema requiere una validación de lectura obligatoria.

| Elemento | Selector | Acción |
|:---------|:---------|:-------|
| **Checkbox LOPD** | `input#lopdok` | Dispara `checkContinuar(this)` al marcarse |
| **Botón Continuar** | `div#botoncontinuar a.naranja` | Ejecuta `javascript:onSave()` |

> [!NOTE]
> El botón **Continuar** solo es visible/interactuable después de marcar el checkbox `#lopdok`.

---

## ⚠️ Observaciones Críticas para la Automatización

| Problema | Solución |
|:---------|:---------|
| **Subdominios** | El flujo cambia de `www.xalocgirona.cat` a `seu.xalocgirona.cat`. Asegurar que el bot no pierda la sesión en el cambio de dominio. |
| **Prefijos DinVar** | Los nombres de los campos son estáticos pero específicos de Xaloc. Si se automatiza otro portal STA diferente, estos IDs podrían cambiar. |
| **Pausas necesarias** | El sistema STA realiza varias peticiones XHR/asíncronas al adjuntar archivos o cambiar de estado. Usar `wait_for_load_state("networkidle")` o esperas explícitas para el botón "Continuar". |



## FASE 7: Revisión y Firma (Paso 2/3)

Una vez pulsado el botón "Continuar" en la fase anterior, el sistema procesa los datos y redirige a la pantalla de revisión final.

### 7.1 Indicadores de Carga
* **URL de Destino:** `https://seu.xalocgirona.cat/sta/Relec/TramitaSign`
* **Comportamiento:** Esta transición suele demorar varios segundos debido a la generación del borrador del documento en el servidor.
* **Estrategia Playwright:**
  ```python
  # Esperar a que la URL cambie y la red se estabilice
  await page.wait_for_url("**/TramitaSign", timeout=30000)
  await page.wait_for_load_state("networkidle")

```

### 7.2 Botón de Envío Final

En esta pantalla se presenta un resumen de todo lo introducido. El botón para finalizar el registro oficial es el siguiente:

* **Selector:** `a.boton-style.naranja:has-text("Enviar")`
* **Atributo HTML:** `<a class="boton-style tamano-defecto naranja" onclick="javascript:comprobar();">Enviar>></a>`

> [!WARNING]
> **POLÍTICA DE TESTEO:** > Para evitar el envío de datos ficticios (dummy data) al registro oficial de la Diputació de Girona, **NO SE DEBE EJECUTAR** el clic en este botón durante las pruebas de automatización. El flujo de test debe finalizar realizando un "Screenshot" de esta pantalla como prueba de éxito.

---

## FASE 8: Finalización y Justificante (Paso 3/3)

Tras pulsar "Enviar" (en un entorno real), el sistema genera el asiento en el registro de entrada.

### 8.1 Elementos de Éxito

* **Resultado:** Descarga de documentación y justificante de registro.
* **Indicador:** Aparición de enlaces o botones para descargar el PDF firmado con el número de registro oficial.

---

## 🛠️ Resumen de Selectores Críticos (Xaloc)

| Elemento | Selector / ID | Acción |
| --- | --- | --- |
| **Email** | `#contact21` | `.fill()` |
| **Denuncia** | `#DinVarNUMDEN` | `.fill()` |
| **Matrícula** | `#DinVarMATRICULA` | `.fill()` |
| **Expediente** | `#DinVarNUMEXP` | `.fill()` |
| **Motivos (Editor)** | `iframe#DinVarMOTIUS_ifr` | `.frame_locator().fill()` |
| **Checkbox LOPD** | `#lopdok` | `.check()` |
| **Continuar (1/3)** | `div#botoncontinuar a` | `.click()` |
| **Enviar (2/3)** | `a:has-text("Enviar")` | **BLOQUEADO EN TEST** |

---

## ⚠️ Consideraciones de Rendimiento

1. **Timeouts:** El sistema STA de Xaloc es propenso a latencias altas en la transición entre la Fase 1 y la Fase 2. Se recomienda un `timeout` de al menos 30 segundos.
2. **Validación Visual:** Debido a que el botón "Continuar" depende de un checkbox con lógica JavaScript (`checkContinuar`), es más seguro usar `page.wait_for_selector("div#botoncontinuar", state="visible")` antes de intentar el clic.

