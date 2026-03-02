## Análisis del selector "Código y nombre del organismo o entidad"

Este selector es **diferente** al de los tipos de vía. Aquí van los hallazgos clave:

---

### Diferencias respecto al selector anterior

| | `dnt-select` (Tipo de vía) | `dnt-select#destinationOrganism` |
|---|---|---|
| `filterable` | `true` | no definido |
| `remote` | `false` | `false` (¡pero en realidad hace API!) |
| Opciones | Pre-cargadas en DOM | Vacío hasta búsqueda |
| Método de búsqueda | `filterMethod` local | `filterMethod` → llama API REST |
| Contenido de opción | `<span>` simple | HTML enriquecido (span + párrafos) |

---

### Qué ocurre internamente

1. Al llamar `el.filterMethod('LA0007892')`, el componente dispara una petición GET a:
   ```
   https://reg-api.redsara.es/dir3/search?searchText=LA0007892
   ```
2. La respuesta popula **dinámicamente** un `dnt-option` con HTML enriquecido en su light DOM:
   ```html
   <dnt-option value="LA0007892">
     <div class="dnt-flex dnt-flex-col">
       <span class="dnt-txt-body-350">LA0007892 - Tribunal Económico-Administrativo Municipal de Madrid</span>
       <p class="dnt-txt-body-200">LA0027329 - Área de Gobierno de Economía, Innovación y Hacienda</p>
       <p class="dnt-txt-body-200">L01280796 - Ayuntamiento de Madrid</p>
     </div>
   </dnt-option>
   ```
3. El click se hace en el `div[role="option"]` dentro del **shadow root** del `dnt-option` (igual que el selector anterior).

---

### Función Playwright para este selector

```javascript
/**
 * Selecciona un organismo en el campo "Código y nombre del organismo o entidad"
 * Usa filterMethod (que hace una llamada a la API dir3) y espera el resultado async.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} codigo - Código DIR3 del organismo (ej: "LA0007892")
 */
async function selectOrganismo(page, codigo) {
  const selectId = 'destinationOrganism';

  // PASO 1: Enfocar el input para que el dropdown esté preparado
  await page.evaluate((id) => {
    const el = document.querySelector(`dnt-select#${id}`);
    const inputEl = el.shadowRoot.querySelector('dnt-input')
      .shadowRoot.querySelector('input.dnt-input__inner');
    inputEl.click();
    inputEl.focus();
  }, selectId);

  // PASO 2: Llamar a filterMethod con el código → dispara GET /dir3/search?searchText=
  await page.evaluate(({ id, code }) => {
    const el = document.querySelector(`dnt-select#${id}`);
    el.filterMethod(code);
  }, { id: selectId, code: codigo });

  // PASO 3: Esperar a que aparezca al menos 1 dnt-option con el valor correcto
  // (la API puede tardar ~300-800ms)
  await page.waitForFunction(
    ({ id, code }) => {
      const el = document.querySelector(`dnt-select#${id}`);
      const opt = el.querySelector(`dnt-option[value="${code}"]`);
      return !!opt?.shadowRoot?.querySelector('[role="option"]');
    },
    { id: selectId, code: codigo },
    { timeout: 10000 }
  );

  // PASO 4: Hacer click en el div[role="option"] dentro del shadow root
  await page.evaluate(({ id, code }) => {
    const el = document.querySelector(`dnt-select#${id}`);
    const opt = el.querySelector(`dnt-option[value="${code}"]`);
    const div = opt.shadowRoot.querySelector('[role="option"]');
    div.click();
  }, { id: selectId, code: codigo });

  // PASO 5: Verificar que el value del componente es el código correcto
  await page.waitForFunction(
    ({ id, code }) => {
      const el = document.querySelector(`dnt-select#${id}`);
      return el.value === code;
    },
    { id: selectId, code: codigo },
    { timeout: 3000 }
  );
}
```

### Uso

```javascript
await selectOrganismo(page, 'LA0007892');
// Selecciona: "LA0007892 - Tribunal Económico-Administrativo Municipal de Madrid"
```

---

### Por qué `page.fill()` + Enter no funciona aquí

Aunque el input acepta texto, el componente **no escucha el evento `input` nativo** del `<input>` interno para lanzar la búsqueda — escucha un evento personalizado que dispara el propio web component `dnt-select` internamente al procesar su estado. Por eso escribir con Playwright o con `dispatchEvent(new Event('input'))` directamente sobre el `<input>` da "Sin datos": el texto aparece en pantalla pero la lógica Angular nunca se activa. La única forma confiable es **llamar directamente a `el.filterMethod(codigo)`** via `page.evaluate()`.