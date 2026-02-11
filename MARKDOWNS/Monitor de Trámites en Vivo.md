# **Monitor de Trámites en Tiempo Real**

Este módulo es el núcleo operativo del sistema. Su función es permitir al supervisor observar la ejecución técnica de los procesos sin interferir, detectando cuellos de botella al instante.

## **1\. El Trámite en Curso (Foco Principal)**

Se sitúa a la izquierda para captar la atención inmediata.

* **Identificador (\#):** Mostrado en fuente grande y negrita (Ej: Trámite \#A478).  
* **Contexto del Recurso:** Detalla el usuario solicitante y el tipo de servicio (Soporte, Administración, etc.).  
* **Progreso Circular:** Un anillo dinámico que se llena según el porcentaje de completitud. Proporciona una métrica visual rápida de "salud" del proceso.  
* **Consola de Eventos (Terminal):** Un área de texto monospaciada con fondo oscuro. Aquí se imprimen los logs técnicos. Los errores deben aparecer en rojo y las confirmaciones en verde.  
* **Cronómetro de SLA:** Ubicado en la base, cuenta el tiempo que el trámite lleva "ocupando" el worker.

## **2\. Cola de Espera**

Ubicada a la derecha, muestra lo que viene a continuación.

* **Tarjetas Compactas:** Cada trámite pendiente se visualiza como una tarjeta con bordes redondeados y una sombra sutil.  
* **Semáforo de Prioridad:** Un indicador de color (Rojo, Amarillo, Verde) que define el orden de salida.

## **3\. Centro de Incidencias**

En lugar de tapar la información, este módulo se presenta como una barra lateral o inferior de alertas.

* **Gravedad:** Clasifica los errores en Críticos, Medios y Leves.  
* **Acción Rápida:** Botón para reintentar el proceso o saltar el trámite fallido.

**Mejora UX:** Se elimina el fondo azul vibrante por un gris pizarra oscuro para reducir la fatiga visual durante turnos largos.