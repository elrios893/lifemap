# Dashboard de Power BI (Entrega 2)

`LifeMap.pbip` es un **proyecto de Power BI** (texto, versionable). Se conecta a la API de LifeMap y no guarda datos: al abrirlo hay que **actualizar**.
Requiere Power BI Desktop (probado con la versión 2.159, Windows).

## Qué muestra (una página, «Panel en vivo»)

| Visualización | Origen (endpoint) |
|---|---|
| Mapa de hotspots (Azure Maps; burbujas por celda, naranja = hotspot) | `/live/hotspots` (una consulta por ventana) |
| Evolución del % de reseñas negativas (línea) y hotspots (columnas) | `/live/trend` |
| Tabla de alertas activas | `/alerts` |
| Curvas de supervivencia por categoría y por zona | `/survival` y `/survival/<categoria>`, `/survival/zone/<zona>` |
| Tarjetas: estado del streaming, retraso del consumidor, alertas vigentes, hotspots | `/health`, `/alerts`, `/live/hotspots` |
| Segmentador de ventana (30 días) | filtra el mapa y la tarjeta de hotspots |

Las consultas están en Power Query (M) dentro del modelo y también copiadas en `consultas.m`.

## Cómo usarlo

1. Abrir `LifeMap.pbip` con Power BI Desktop.
2. **Elegir la API:** `Transformar datos` → `Administrar parámetros` → `ApiUrl`.
   - Local: `http://localhost:5050` (valor por defecto).
   - Nube: `https://unmovable-crumpet-opposite.ngrok-free.dev` (con la VM encendida) o `http://<IP de la VM>`.
3. Pulsar **Actualizar** (pestaña Inicio). La primera vez Power BI puede pedir credenciales del origen web: elegir **Anónimo**.
4. Para la demostración en vivo, con el flujo en marcha, **pulsar Actualizar cada pocos segundos**.

## Limitación que hay que decir

Power BI Desktop trae los datos de una API web en modo **importación**: no se actualiza solo, hay que pulsar *Actualizar* (o programarlo en el servicio de Power BI,
con un mínimo de 30 minutos). El actualizado automático de página solo existe para fuentes DirectQuery. Por eso la demo se hace refrescando a mano.

## Notas técnicas

- Lo valida el propio Power BI al abrir: modelo semántico en TMDL (`LifeMap.SemanticModel`) e informe en formato PBIR (`LifeMap.Report`).
- Los endpoints usados están probados en `tests/test_live.py`. `/survival` (sin categoría) es el listado que usa el modelo para saber qué curvas pedir.
- La actualización de la tabla `survival` hace una petición por curva (hasta 8 categorías y 8 zonas).
- `.pbi/` y `cache.abf` son locales y están en el `.gitignore`.
