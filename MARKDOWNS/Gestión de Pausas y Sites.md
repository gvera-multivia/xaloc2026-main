# **Control Administrativo y Gestión de Sites**

Esta sección permite al administrador "abrir o cerrar el grifo" de los trámites que entran al sistema, ya sea de forma global o específica por ubicación.

## **1\. Pausa Global Rápida**

Es un panel de emergencia o mantenimiento programado.

* **Input de Tiempo:** Permite definir cuántos minutos durará la pausa.  
* **Motivo de Pausa:** Un campo obligatorio para la auditoría posterior.  
* **Botón de Acción:** Destacado para pausar todos los flujos visibles con un solo clic.

## **2\. Control por Site (Madrid, Girona, etc.)**

Una tabla detallada que desglosa la capacidad operativa de cada sede.

* **Métricas de Site:** Total en cola, trámites pendientes y trámites procesándose actualmente.  
* **Etiquetas de Estado:** ACTIVO (Verde) o PAUSADO (Rojo).  
* **Acciones por Fila:** Botones específicos para:  
  * **Pausar:** Detener el flujo de ese site.  
  * **Pausa sin límite:** Para mantenimientos indefinidos.  
  * **Reanudar:** Volver a activar el worker para ese origen.

## **3\. Control por Elemento de Cola**

Permite una micro-gestión. Si un trámite específico está bloqueando el sistema, el administrador puede pausar **solo ese elemento** sin afectar al resto del site.

**Mejora UX:** Se añade una confirmación visual (Modal) antes de realizar una Pausa Global para evitar clics accidentales catastróficos.