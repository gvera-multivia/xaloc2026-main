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

El contenido copiado del original está en `base-reposicion-form.html`
Pero lo relevante es el contenido del formulario y los datos especificos que necesitamos tratar como variables para enviarlos al formulario.

Y esos trozos importantes son:

1 - Los inputs de tipo radio

```
<div class="fieldset-in">
	<div class="inputs-container">
		<div class="input-item info">
			<p>Cada tipus d'objecte requereix una dada específica que l'identifica i que heu d'indicar en el camp <strong>Dades específiques</strong>. A més, en cas d'existir un rebut relacionat amb la vostra sol·licitud us agrairem que ens faciliteu la seva clau de cobrament. Recordeu també que en cas de que es practiqui una devolució també ens heu d'informar del vostre <strong>número de compte</strong>. 
				</p>
			</div><span class=""><input id="form0:tipusObjecteHidden" type="hidden" name="form0:tipusObjecteHidden" value="1">
					<div class="input-item ">
						<input type="radio" id="radio1" name="radiooo" class="input" onclick="setTipusObjecte('1')"><strong>IBI</strong> - Referència cadastral del immoble - <strong>xxxxxxxxx</strong>
					</div>
					<div class="input-item ">
						<input type="radio" id="radio2" name="radiooo" class="input" onclick="setTipusObjecte('2')"><strong>IVTM</strong> - Matrícula del vehícle - <strong>xxx-YYY</strong>
					</div>
					<div class="input-item ">
						<input type="radio" id="radio3" name="radiooo" class="input" onclick="setTipusObjecte('3')"><strong>Expedient Executiu</strong> - Número d'expedient - <strong>xxxx/yyyy</strong>
					</div>
					<div class="input-item ">
						<input type="radio" id="radio4" name="radiooo" class="input" onclick="setTipusObjecte('4')"><strong>Altres</strong> - Número fix - <strong>xxxxxxxxx</strong>
					</div>
				
				<script type="text/javascript">
					function setTipusObjecte(valor) {
						document.getElementById("form0:tipusObjecteHidden").value = valor;
							document.getElementById("radio1").checked = valor === '1';
							document.getElementById("radio2").checked = valor === '2';
							document.getElementById("radio3").checked = valor === '3';
							document.getElementById("radio4").checked = valor === '4';
					};
					setTipusObjecte('1');
				</script></span>
				
				
				<div class="input-item ">
					<label for="dades"> Dades específiques: <span class="required">*</span></label><br><textarea id="form0:dades" name="form0:dades" class="input" cols="70" rows="5"></textarea>
				</div>								
			</div>
		</div>
```

El valor del parametro que se enviará para esto en concreto sera el número que identifique al input que se marque en el radio button.