# MCP Debug Loop

## Secuencia minima

1. abrir la pagina objetivo
2. sacar snapshot accesible
3. interactuar con el siguiente paso real del flujo
4. volver a snapshot
5. revisar consola si algo diverge
6. revisar red si hay navegacion rara, 4xx, 5xx o descargas
7. repetir hasta localizar la primera rotura real

## Prioridades

- snapshot antes que screenshot
- consola antes de asumir selector roto
- red cuando el DOM parece correcto pero la accion no progresa

## Cuando parar

- cuando ya se conoce el primer paso roto y la razon tecnica mas probable
- no seguir navegando si la evidencia ya apunta claramente al archivo a corregir
