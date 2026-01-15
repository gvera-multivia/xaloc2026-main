# Guia de movimientos dentro de los diferentes HTML:

## 1 - Landing

Se encuentra en:
`https://www.base.cat/ciutada/ca/tramits/multes-i-sancions/multes-i-sancions.html`
Una vez dentro se tiene que clicar en este componente que se muestra a continuación. Este componente forma parte de la landing de Base, de la cual hay una copia en `explore-html\base-landing.html``

```
<a href="https://www.base.cat/sav/valid" class="logo_text" data-insuit-uuid="49d09886-c1f1-4580-8cff-7f086cf0b37d">
    <span class="icon-online"></span>
    <span>Base On-line</span>
</a>
```

## 2 - Certificado
La base se debe de detectar con un regex igual que previamente en xaloc, ya que usa uuids, un ejemplo es:

`https://valid.aoc.cat/o/oauth2/auth?client_id=tramits.base.cat&redirect_uri=https://www.baseonline.cat/sav/code&state=/commons-desktop&scope=autenticacio_usuari&response_type=code&access_type=offline&approval_prompt=auto`

En este caso el proceso es el mismo que en el caso de xaloc. Por tanto podemos replicar el proceso en `flows\login.py`Se debe de accionar el boton:
```
<button id="btnContinuaCert" data-testid="certificate-btn" data-toggle="modal" class="btn btn-opc btn-certificatDigital">
    <span class="txt">Certificat digital:</span>
    <span class="info">idCAT, DNIe ...</span>
</button>
```
Una vez clicado, usamos el pyautogui de forma paralela con playwright y ya estaría, insisto, mismo proceso siempre porque es una pagina de autenticación del estado.

## 3 - Common Desktop

En esta 3ª pantalla nos encontramos con una nueva url que es:
`https://www.baseonline.cat/commons-desktop/index.html`

Aqui econtramos el contenido que se muestra en `base-common.html `
Pero de todo el contenido de las tablas, lo unico relevante es:

P1- El acceso al formulario de identificación de conductor

```
<a href="/pst/flow/formulari?tramit=M250" title="Sol·licitud d'identificació de conductor"><span><span>Sol·licitud d'identificació de conductor</span></span></a>
```

P2- El acceso al formulario de alegaciones

```
<a href="/pst/flow/formulari?tramit=M203" title="Al·legacions en el procediment sancionador en matèria de trànsit"><span><span>Al·legacions en el procediment sancionador en matèria de trànsit</span></span></a>
```

P3- El acceso al formulario de reposición

```
<a href="/gir-ciutada/flow/recursTelematic" title="Recurs de reposició">Recurs de reposició</a>
```

Esto es muy importante, porque en esta web, cuando estamos en esta pagina NECESITAMOS especificar el protocolo concreto ya sea P1, P2 o P3.
Dependiendo de ello, seleccionaremos un formulario u otro, es decir, que este es un punto de ramificación del workflow en funcion del protocolo.
Como veremos a continuación cada uno de los formularios tiene diferentes datos y procesos.


## 4 - Ramificaciones

Como hemos dicho, debemos permitir diferentes posibles rutas de acceso.

### 4.1 - Formulario de Reposición (P3)

