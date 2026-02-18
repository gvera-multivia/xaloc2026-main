# Refarctorización del frontend (USER)

QUeremos refacotrizar un pocco la pagina del frontend que ven los usuario (NO ADMINS) de MORRIGAN.

Ahora mismo pueden ver la pantalla de Gestion y la de historial de tareas.

### Pantalla de bloqueos
Queremos que ademas de eso tengan acceso a la pantalla de bloqueos, que puedn desbloquear los recursos. Es mas queremos generar una nueva version de la pagina de bloqueso tanto para los admins como para las abogadas.
La idea es que haya 3 opciones: 
1- Eliminar (El recurso ya lo ha hecho manualmente alguien):
    En este caso simplemente olvidamos el bloqueo, porque ya no es necesaria su existencia.
2- Desbloquear:
    Este es el caso de funcionamiento actual del recurso, simplemente lo desbloqueamos.
3- Reintentar:
    Este caso es similar al desbloqueo, pero no solo desbloquea sino que ademas hace una llamada para que se vuelva a hacer todo el proceso de reclamacion de recurso, generacion del payload y demás.

### Pantalla de GEstion

Queremos que tengan acceso a la pantalla de gestion pero sin que fuedan ver los botones de pausa, simplemente que puedan ver el estado y las colas y las autorizaciones pendientes (Y tengan la potestad de Autorizarlas o Rechazarlas).

Queremos ademas eliminar eliminar el campo de Incidencias recientes porque eso ya se ve en otra pantalla (Tanto para admin como para usuario normal).

