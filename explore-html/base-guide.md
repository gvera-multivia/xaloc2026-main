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