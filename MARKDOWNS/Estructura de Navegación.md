# **Sistema de Navegación Global (Navbar)**

La Navbar es el elemento de consistencia que permite al usuario moverse entre el monitoreo reactivo y la administración proactiva.

## **1\. Componentes de la Navbar**

* **Branding:** Logo del sistema y nombre de la herramienta.  
* **Enlaces de Sección:**  
  * **Dashboard:** Acceso al Monitor en Vivo (Vista de procesos y cola).  
  * **Administración:** Acceso al Panel de Pausas y Sites.  
  * **Historial:** Acceso a la página de Auditoría por día.  
* **Utilidades:**  
  * **Buscador rápido:** Un atajo para encontrar un trámite sin importar en qué página estés.  
  * **Estado del Worker:** Un pequeño indicador (LED verde/rojo) que muestra si el motor de procesamiento global está encendido.  
  * **Perfil de Usuario:** Acceso a configuración y cierre de sesión.

## **2\. Comportamiento y UX**

* **Estado Activo:** El enlace de la sección donde se encuentra el usuario debe estar resaltado con un subrayado o cambio de color (ej. Morado o Azul suave).  
* **Persistencia:** La Navbar debe estar "pegada" (Sticky) en la parte superior para que el usuario pueda cambiar de sección sin importar cuánto scroll haya hecho en el historial.

**Mejora UX:** Se implementan "Breadcrumbs" (Migas de pan) debajo de la Navbar (ej: Home \> Historial \> 11/02/2026) para que el usuario nunca pierda el sentido de ubicación.