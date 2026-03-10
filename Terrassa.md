Ajuntament de Terrassa
(consideremos que este tramite puede hacerse en varios lenguajes, asi que no basemos ninguna decision de filtrado de campos o clics en el contenido textual de los elementos)


https://aoberta.terrassa.cat/tramits/fitxa.jsp?id=3822

En la pagina clicamos en <a href="/tramits/ferTramit.jsp?id=3822" title="Cal estar identificats per fer aquest tràmit" class="boto_portada tramitar">

            Ompliu el formulari  <i class="fa fa-lock" aria-hidden="true" style="font-size: 1.5em;"></i>
            
            
                (id. obligatòria)
            
        </a>

Si estamos identificados nos dejara pasar directamente al formulario sino nos pedira mas cosas antes, pero hay que tener en cuenta que en el codigo que saquemos en playwright, el flujo debe considerar la opcion que tras el boton nos lleve directamente al formulario y no pete por timeout de espera a la identificacion y que en el identificacion no pete por timeout de espera al formulario.

Entonces le dariamos a identificar.

<a class="boto_portada" style="margin:0 auto; color: #4777d1;" href="/demanaIdentitat">Identifiqueu-vos <i class="fa fa-angle-right"></i></a>

Entonces nos llevaria al https://valid.aoc.cat/o/oauth2/auth? donde clicamos aqui:

<button id="btnContinuaCertCaptcha" data-toggle="modal" class="g-recaptcha btn btn-opc btn-certificatDigital" data-sitekey="6Lfji0wnAAAAAF4KoRbd_5eL1KfymxxxqNPP3CkI" data-callback="submitCertificat" data-action="submit">
                          <span class="txt">Certificat digital:</span>
                      <span class="info">idCAT, DNIe ...</span>
                    </button>

Y saldra un selector de certificado (eso lo clicare yo) y eso nos llevará directos al formulario

Una vez en el formulario:


Primero clicamos en vinculo de actuar como representante:
<div style="text-align: center;" class="botoGrisGros">
                                        <a href="/accions/identificaRepIntercanvi">
                                        Vull actuar com a representant</a> <br>(fer la sol·licitud en nom d'una altra persona)
                                    </div>

Tras eso la pagina se actualizará.

Entonces, en primer lugar necesitamos saber si es una empresa o un particular. Si es una empresa, seleccionaremos o la opcion de CIF o la opcion de documento de identificacion extrangero juridico en el selector, sino seleccionaremos nif o el documento que toque a la persona fisica en el siguiente selector:

<select name="IDPersona_TD" style="width:90%" onchange="IDPersona_ND.value=validaTipusDocument(this.value,IDPersona_ND);mostraAmagaDades();" id="IDPersona_TD" class="text">
						  <option value="">Seleccioneu el tipus de document</option>
					<option value="1">DNI / NIF</option>
					<option value="3">NIE</option>
					<option value="7">CIF o entitats</option>
					<option value="2">Passaport estranger</option>
					<option value="2">Document d'identificació estranger</option>
					<option value="10">Doc. d'identificació jurídic estranger</option>
				</select>
En funcion de si es empresa o particular los campos cambiaran para identificar a una empresa o para identificar a un particular.

Entonces pones el numero de documento en el siguiente campo
<input type="text" name="IDPersona_ND" style="width:45%" maxlength="20" value="" onfocus="mostraCapa('help_IDPersona');" id="IDPersona_ND" onblur="this.value=validaTipusDocument(IDPersona_TD.value,this);amagaCapa('help_IDPersona');">
Y la razon social en este campo:
<input type="text" name="nom" id="nom" style="width:90%" maxlength="40" value="" onblur="this.value=majusculaString(validaTextNumero(this));" title="Nom o raó social, màx. 40 caràcters">


Sin embargo si fuera una persona fisica, el proceso es algo diferente porque hay mas campos.

Pondias el valor de documento:
<input type="text" name="IDPersona_ND" style="width:45%" maxlength="20" value="" onfocus="mostraCapa('help_IDPersona');" id="IDPersona_ND" onblur="this.value=validaTipusDocument(IDPersona_TD.value,this);amagaCapa('help_IDPersona');">

Pondrias el nombre:

<input type="text" name="nom" id="nom" style="width:90%" maxlength="40" value="" onblur="this.value=majusculaString(validaTextNumero(this));" title="Nom o raó social, màx. 40 caràcters">
Pondrias el primer apellido:

<input type="text" name="cognom1" id="cognom1" style="width: 90%; display: block;" maxlength="30" value="" onblur="this.value=majusculaString(validaText(this));" title="Primer cognom, màx. 30 caràcters">

Y pondrias el segundo apellido (en caso de que tenga asi que es opcional)

<input type="text" name="cognom2" style="width: 90%; display: block;" maxlength="30" id="cognom2" value="" onblur="this.value=majusculaString(validaText(this));" title="Segon cognom, màx. 30 caràcters">



Una vez hecho esto, bajariamos hasta el campo de numero de expediente:
<input type="text" name="_NUM_EXPEDIENT" id="_NUM_EXPEDIENT" maxlength="10" size="10" onblur="this.value=cridaControl('A', this);" value="">

Pondremos la fecha de infraccion:

<input type="text" name="_DATA_FET" id="_DATA_FET" maxlength="10" size="10" onblur="this.value=cridaControl('D', this);" value="">

Pondremos matricula del vehiculo:

<input type="text" name="_MATRICULA" id="_MATRICULA" maxlength="15" size="15" onblur="this.value=cridaControl('A', this);" value="">

Y pondremos marca del vehiculo ( a efectos practicos esto nunca lo tendremos asi que simplemente pondremos Otros.
<input type="text" name="_MARCA" id="_MARCA" maxlength="15" size="15" onblur="this.value=cridaControl('A', this);" value="">


Luego pondremos las alegaciones:

<textarea name="_MOTIUS" id="_MOTIUS" rows="7.666666666666667" cols="60" wrap="virtual" onkeydown="limitText(this.form._MOTIUS,400);" onkeyup="limitText(this.form._MOTIUS,400);"></textarea>

Y las observaciones:

<textarea name="_OBSERV" id="_OBSERV" rows="7.666666666666667" cols="60" wrap="virtual" onkeydown="limitText(this.form._OBSERV,400);" onkeyup="limitText(this.form._OBSERV,400);"></textarea>


Luego hay que poner una descripcion del archivo que subiremos a continuacion.
<input type="text" name="descripcio" value="" size="22" maxlength="79" placeholder="Breu descripció/títol del document">
Por ejemplo si es una autorizacion ponemos autorizacion.

Luego en el select seleccionamos el tipo:

<select name="tipologia_documental" style="font-size: 12px; padding: 4px; font-family: Arial, helvetica !important;" onchange="document.fitxers1.descr_tipologia_documental.value=document.fitxers1.tipologia_documental.options[document.fitxers1.tipologia_documental.selectedIndex].text;"> <option value="-">Seleccioneu un tipus de la llista</option><option value="U074_W">Al·legació</option><option value="U138_W">Autorització</option><option value="U141_W">Carnet</option><option value="U022_W">Certificat</option><option value="U118_W">Contracte</option><option value="U014_W">Conveni</option><option value="U125_W">Currículum</option><option value="U135_W">Document Nacional Identitat - NIF</option><option value="U152_W">Document Identitat Estranger - NIE</option><option value="U061_W">Escriptura</option><option value="U033_W">Factura</option><option value="U057_W">Fotografia</option><option value="U006_W">Informe</option><option value="U112_W">Justificant</option><option value="U009_W">Memòria</option><option value="U027_W">Notificació</option><option value="U058_W">Plànol</option><option value="U139_W">Poders notarials</option><option value="U145_W">Pressupost</option><option value="U045_W">Projecte</option><option value="U006_W">Resolució</option><option value="U107_W">Sentència</option> </select>

Y luego subiriamos el archivo:

<div style="margin: 0px; padding: 1px 5px 1px 5px; float: left; text-align: left;">   <br><input type="hidden" value="1" name="numFitxer">   <input type="hidden" name="fitxerPle" value="">    <input type="hidden" name="idTramit" value="3822">   <input id="fileUpload1" name="fileUpload1" type="file" onchange="javascript: document.fitxers1.fitxerPle.value=&quot;ple&quot;;ferSubmitFitxer(1,document.fitxers1.descripcio.value,document.fitxers1.fitxerPle, document.fitxers1.tipologia_documental.value);" style="width: 210px;">   <iframe name="iframeUpload1" class="ocult" src=""></iframe></div>

Cuando subimos un documento se actualiza la pagina y tenemos que volver abajo para subir mas si queremos mas. (haz 2 subidas de documentos)

Luego le damos a continuar.
<a href="#" onclick="if (comprovaFormulari()) document.solicitud.submit();" style="color: #51923C;" class="boto_portada">
			<strong>Continuar</strong>  <i class="fa fa-chevron-right" aria-hidden="true" style="font-size: 1.6em;"></i></a>

Te saldria una pantalla con un boton abajo de Firmar, PERO no vamos a firmar, nos detenemos aqui, por ahora aqui acaba el tramite y me consigues el codigo de playwright para automatizar el proceso. Importante, NO firmamos.





