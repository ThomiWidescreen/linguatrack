# Verificación del backend local

Fecha: 20 de noviembre de 2026, Asia/Kuala_Lumpur.

## Comprobaciones ejecutadas

- 18 pruebas backend sobre PostgreSQL con pgvector, en una base aislada creada para el test: aprobadas. Incluyen concurrencia de submits/publicaciones, replay, outbox, lease vencido, runs obsoletos, correcciones, RLS y citas inexistentes.
- 15 pruebas existentes del pipeline léxico: aprobadas, sin modificar el pipeline.
- Ruff lint y formato: aprobados.
- `alembic check`: sin diferencias pendientes entre modelos y migraciones.
- `docker compose config --quiet`, build e inicio de DB, Redis, API, worker y dispatcher: correctos.
- `/health/ready`, `/docs` y `/openapi.json`: disponibles en `http://localhost:8001`.

La suite backend usa un extractor controlado y no consume OpenAI. Hay una advertencia de deprecación del TestClient de Starlette al usar httpx; no afecta los resultados actuales.

## Prueba real de extracción

Se enviaron las dos clases de malayo del diseño usando la clave de `.env`, OpenAI Responses API y `gpt-4.1-mini`, atravesando HTTP → outbox → Redis/Dramatiq → worker → PostgreSQL. Las publicaciones finales completaron en un intento por revisión y quedaron disponibles en el usuario demo.

| Clase | Publicación final |
|---|---|
| 1 | Tres lexemas nuevos: walaupun, terpaksa, sempat; una construcción concesiva; sin aciertos independientes atribuidos |
| 2 | Dos lexemas nuevos: meskipun, berpeluang; dos revisitados: walaupun, sempat; un acierto independiente reportado |

El progreso final muestra cinco lexemas encontrados y una construcción, con evidencia de producción correcta para walaupun. No se asignan probabilidad de dominio ni nivel CEFR. Las revisiones anteriores se conservaron para verificar el reprocesamiento sin contribución duplicada.

La validación detectó índices de citas incorrectos y variaciones de clasificación del modelo. Se añadieron localización determinista de citas únicas, instrucciones más precisas y reglas versionadas de normalización de etiquetas léxicas, con pruebas de regresión. No se reparan citas que no existen ni se escoge automáticamente entre ubicaciones ambiguas.

Esto verifica el recorrido funcional y un ejemplo lingüístico concreto; no constituye una evaluación estadística de calidad multilingüe. El alcance pendiente y las instrucciones para probar están en [la guía del backend](../apps/backend/README.md).
