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

## Actualización: objetivo e idiomas puente

El extractor `lesson-v3` distingue el objetivo del track de los idiomas puente opcionales. La migración `0003` agrega el contexto a sesiones y runs con valor vacío para datos anteriores. El contexto original queda protegido por el trigger de inmutabilidad; cada reprocesamiento puede conservarlo, reemplazarlo o volver al modo automático.

- 30 pruebas backend aprobadas, incluyendo entrega del contexto al proveedor, rechazo de evidencia del idioma puente, cambios de contexto por revisión, idempotencia compatible e inmutabilidad del envío original.
- `alembic check`: sin diferencias pendientes después de aplicar `0003`.
- Smoke real con un fixture sintético de equivalencias español/malayo/inglés: recuperó `tidur`, `kadang-kadang` y `di suatu tempat`, conservó sus citas y excluyó traducciones de español/inglés. Pasó con `bridge_languages=[]` y con `["es", "en"]`, sin advertencias por mezcla ni construcciones inventadas.
- Se verificó un reprocesamiento completo por HTTP y worker, manteniendo la publicación anterior hasta el éxito. El contenido privado usado para esa comprobación no se incorpora al repositorio.

Las pruebas de proveedor son acotadas y separadas de CI. Estos casos no establecen una tasa de precisión ni garantizan cobertura exhaustiva de todo apunte multilingüe.

## Actualización: reconciliación contextual y conflictos de glosa

- 39 pruebas backend aprobadas. Las regresiones cubren cambios de POS con una identidad duplicada preexistente, homógrafos con igual escritura/POS, traducciones entre idiomas puente, conflictos de significado, reutilización de extracción e idempotencia del checkpoint de comparación.
- Migración `0004` aplicada y `alembic check` sin diferencias pendientes. El run guarda los candidatos, decisiones, razones y metadatos del proveedor antes de publicar.
- Prueba real mediante HTTP → outbox → worker, reutilizando una extracción publicada y ejecutando solo la nueva comparación contextual: se enlazó una variante de POS al concepto anterior y se señalaron diferencias de glosa para revisión. La proyección efectiva conservó un solo registro para la identidad reconciliada, sin editar observaciones anteriores.
- El proyector `counts-v2` preserva el resultado reportado de un intento pero excluye aciertos con significado pendiente de revisión de los contadores de demostración.

Las decisiones contextuales son heurísticas de modelo con candidatos acotados. Los conflictos indicados son solicitudes de revisión, no correcciones lingüísticas certificadas. No se publican aquí textos privados ni identificadores de clases usadas para verificar el flujo.
