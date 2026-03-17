
# Lógica de tramitación de expedientes con CSV

## 1. Comprobación inicial: existencia de CSV

El primer paso del flujo consiste en comprobar si el expediente **dispone de CSV**.

El CSV se obtiene desde:

```
expediente.ExpedientePublicacion
```

### Resultado posible

#### Caso 1 — El expediente **tiene CSV**

Se debe determinar **qué tipo de procedimiento es**.

Para ello se consulta la columna:

```
recursos.recursosExp.Procedim
```

El valor de esta columna indicará si se trata de:

* **Reclamación Económico-Administrativa (REA)**
* **Recurso de Reposición**

---

# 2. Identificación del tipo de recurso mediante Regex

Para identificar correctamente el tipo de procedimiento se utilizan **expresiones regulares robustas**, capaces de manejar abreviaturas, variaciones de escritura y separadores.

---

# 2.1 Regex para Reclamación Económico-Administrativa (REA)

```regex
/(RECLAMACION\s+(ECONOMICO|ECO)[- ]*(ADMINISTRATIVA|ADVA)|(?<!\w)REA(?!\w))/i
```

### Funcionamiento

Esta expresión detecta:

1. La frase completa **“Reclamación Económico-Administrativa”** con variaciones.
2. Abreviaturas del término.
3. Las siglas **REA** cuando aparecen como palabra independiente.

### Detalles técnicos

* `RECLAMACION\s+`
  Detecta la palabra *Reclamación* seguida de uno o más espacios.

* `(ECONOMICO|ECO)`
  Permite detectar tanto **ECONOMICO** como la abreviatura **ECO**.

* `[- ]*`
  Permite que exista:

  * un guion
  * un espacio
  * o ninguno

* `(ADMINISTRATIVA|ADVA)`
  Detecta:

  * **ADMINISTRATIVA**
  * **ADVA** (abreviatura)

* `(?<!\w)REA(?!\w)`
  Detecta **REA** solo si aparece como **palabra aislada**, evitando falsos positivos dentro de otras palabras (por ejemplo: *AREA*).

---

# 2.2 Regex para Recurso de Reposición (incluyendo extraordinarios)

```regex
/(RECURSO\s+(EXTRAORDINARIO|REVISION|DE\s+REPOSICION)|(?<!\w)REPOSICION(?!\w))/i
```

### Funcionamiento

Esta expresión detecta:

* **Recurso extraordinario**
* **Recurso de revisión**
* **Recurso de reposición**
* La palabra **Reposición** por sí sola

### Detalles técnicos

* `RECURSO\s+`
  Busca la palabra *Recurso* seguida de espacios.

* `(EXTRAORDINARIO|REVISION|DE\s+REPOSICION)`
  Detecta las diferentes variantes del tipo de recurso.

* `(?<!\w)REPOSICION(?!\w)`
  Detecta la palabra **Reposición** como palabra independiente, evitando coincidencias parciales.

---

# 3. Flujo según tipo de recurso

Una vez identificado el tipo de procedimiento, se ejecuta el flujo correspondiente.

### CSV + Reclamación Económico-Administrativa

Se ejecuta el flujo definido en:

```
flujos-atc\flujo-reclamacio-economicoadministrativa.md
```

---

### CSV + Recurso de Reposición

Se ejecuta el flujo definido en:

```
flujos-atc\flujo-recurs-reposicio.md
```

---

# 4. Caso en el que NO existe CSV

Si el expediente **no dispone de CSV**, se ejecuta el flujo alternativo definido en:

```
flujos-atc\flujo-sin-cvs.md
```

---

# 5. Módulo adicional: clientes con restricción de subida

Se implementa un **módulo adicional** para determinados clientes que **no desean que se suban recursos a la web hasta el último día del plazo**.

Actualmente esta regla aplica a los clientes:

```
13607
14274
```

---

## Regla de bloqueo

Un recurso **no debe seleccionarse ni tramitarse** hasta que se cumpla la siguiente condición:

```
fecha actual == recursos.recursosExp.fecpres
```

El campo `fecpres` tiene formato:

```
YYYY-MM-DD
ejemplo: 2026-04-09
```

Hasta que no llegue esa fecha exacta, el expediente **no se procesa**.

---

# 6. Organismo competente

El organismo contra el que se interpone la reclamación se identifica en la base de datos mediante:

```
LIKE %AGENCIA TRIBUTARIA AUTONOMICA DE CATALUÑA%
```

---

# 7. Patrones válidos de números de expediente

Los expedientes pueden aparecer en múltiples formatos.
A continuación se listan **todos los patrones válidos detectados**.

| Patrón                                             | Total Expedientes | Ejemplo real                                   |
| -------------------------------------------------- | ----------------- | ---------------------------------------------- |
| `###############`                                  | 3278              | 949820222793343                                |
| `DIL###########`                                   | 1129              | DIL20260636234                                 |
| `##############`                                   | 268               | 94522026115872                                 |
| `DIL##########`                                    | 171               | DIL2020041044                                  |
| `############## ###############`                   | 107               | 20250001573564 945220258040938                 |
| `############## DIL###########`                    | 33                | 20260000159527 DIL20260092644                  |
| `##############  ###############`                  | 6                 | 20250001495390  945220258901171                |
| `#############`                                    | 6                 | 2180001172904                                  |
| `####################`                             | 3                 | 94522022729216538081                           |
| `########G`                                        | 2                 | 46350156G                                      |
| `##############  DIL###########`                   | 2                 | 20240001360583  DIL20242297250                 |
| `############## -###############`                  | 2                 | 20250001588500 -945220258855378                |
| `C################`                                | 2                 | C0900025080625572                              |
| `############## ##YXC#S###VVERAL#SYM`              | 1                 | 20250000713557 36YXC1S294VVERAL1SYM            |
| `##############- DIL###########`                   | 1                 | 20240000297542- DIL20232101228                 |
| `########A DIL###########`                         | 1                 | 46702860A DIL20252335832                       |
| `############## ############P`                     | 1                 | 20250001441243 082520746290P                   |
| `DIL########### ############## ###############`    | 1                 | DIL20232409778 20240000575808 945220227533549  |
| `###############T`                                 | 1                 | 945220201431198T                               |
| `DIL########### CSV##AQ#FN#VJ#D#GRCV#ONa`          | 1                 | DIL20260132416 CSV30AQ4FN6VJ6D5GRCV0ONa        |
| `########W`                                        | 1                 | 79280174W                                      |
| `J ##############`                                 | 1                 | J 20180000953556                               |
| `############# #S#GMAWF#WPP#JPVH#QM`               | 1                 | 2025000085703 3S1GMAWF4WPP7JPVH8QM             |
| `DIL###############`                               | 1                 | DIL202406642831050                             |
| `############## #MM#YHS#S##DPRJ#IKB#`              | 1                 | 20250000247796 3MM2YHS8S73DPRJ6IKB1            |
| `DIL###########b`                                  | 1                 | DIL20232827909b                                |
| `############## ##AMG##YXELNAXPBIJ#H`              | 1                 | 20250000852293 36AMG10YXELNAXPBIJ2H            |
| `############### ##/########`                      | 1                 | 945220242624724 08/35170348                    |
| `############## #GFUW#OJ#YLKO#FOA#BZ`              | 1                 | 20250000191199 3GFUW2OJ4YLKO9FOA9BZ            |
| `##############.pdf`                               | 1                 | 20240001368363.pdf                             |
| `##############  #SRNJLMW##T#RDH#VLD#`             | 1                 | 20250000247849 3SRNJLMW11T6RDH6VLD6            |
| `##/########-#`                                    | 1                 | 08/35273400-9                                  |
| `DIL########### DIL###########`                    | 1                 | DIL20232228319 DIL20241072551                  |
| `##############  ###############  ###############` | 1                 | 20250000809865 945220243984412 945220243883388 |
| `DIL########### #CEF#S#F##HQCUWF#OHI`              | 1                 | DIL20260119085 3CEF8S7F12HQCUWF4OHI            |
| `###############.pdf`                              | 1                 | 945220259559895.pdf                            |
| `############## ################`                  | 1                 | 20250000909620 9452202582436799                |
| `########P`                                        | 1                 | 38796523P                                      |
| `MU############### - MU###############`            | 1                 | MU202140010031262 - MU202040000157428          |
| `DIL#########`                                     | 1                 | DIL201904705                                   |
| `DIL########### #GSGJ##LO#H#E#T###AI`              | 1                 | DIL20260124477 3GSGJ91LO8H8E5T542AI            |

---

# 8. Casos con múltiples expedientes en un mismo campo

En algunos registros el campo expediente **contiene varios números separados por espacios**.

Ejemplo:

```
20250001488736 945220258915702
```

Esto **no significa que el expediente tenga ese formato**, sino que el campo contiene **varios números y solo uno es el correcto**.

---

# 9. Método para determinar el expediente real

Para identificar cuál es el expediente válido se realiza el siguiente proceso:

1. Separar los números de expediente.
2. Consultar cada uno en la tabla `expedientes`.

Ejemplo:

```sql
select * from expedientes where numexpediente = '20250001488736'

select * from expedientes where numexpediente = '945220258915702'
```

### Interpretación del resultado

* Uno de los dos resultados **devolverá registros**.
* El otro **no devolverá resultados**.

El expediente **que no tiene registros en la tabla `expedientes` es el expediente correcto**.

En el ejemplo:

```
20250001488736 → sin resultados → expediente correcto
945220258915702 → con resultados → no es el correcto
```

---

# 10. Caso excepcional: tres expedientes

En el caso extremadamente raro de que aparezcan **tres expedientes**, no se puede aplicar el método anterior de verificación.

En ese caso se utiliza una regla simplificada:

```
Se toma el primer expediente del listado.
```

---
