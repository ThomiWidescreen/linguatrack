# LinguaTrack backend

MVP local con Python 3.12+, FastAPI, SQLAlchemy, Alembic, PostgreSQL/pgvector, Redis, Dramatiq y OpenAI Responses API con salida Pydantic estructurada. La API y el worker comparten reglas de dominio; los trabajos aceptados se conservan en PostgreSQL mediante outbox.

## Inicio rápido

Desde la raíz del repositorio, crear `.env` a partir de `.env.example` **solo si no existe** y configurar `OPENAI_API_KEY`. El archivo real está ignorado por git y excluido del build de Docker. No hace falta copiar la clave al código. `OPENAI_MODEL` es configurable y por defecto usa `gpt-4.1-mini`.

```sh
docker compose up --build -d
docker compose ps
```

Las migraciones corren automáticamente antes de API, worker y dispatcher. Los datos sobreviven a reinicios mediante volúmenes.

- Swagger interactivo: <http://localhost:8001/docs>
- ReDoc: <http://localhost:8001/redoc>
- Contrato OpenAPI: <http://localhost:8001/openapi.json>
- Readiness de DB y Redis: <http://localhost:8001/health/ready>
- Usuario local actual: <http://localhost:8001/v1/me>

Los puertos se publican en `127.0.0.1`. PostgreSQL usa 5433 y Redis 6380 para procesos del host. Las credenciales del Compose son exclusivamente locales. `ENVIRONMENT=production` se rechaza hasta implementar autenticación.

## Probar desde Swagger

1. `POST /v1/me/languages` con `{"language_tag":"ms"}`. Copiar el `id` del track. Si ya existe, consultarlo con `GET /v1/me/languages`.
2. `POST /v1/me/languages/{track_id}/sessions`: completar track y `Idempotency-Key`, por ejemplo `malay-class-1`. El body de ejemplo ya contiene la primera clase:

```json
{
  "title": "Clase de malayo 1",
  "text": "Today we learned walaupun (although), terpaksa (being forced to), and sempat (having time to do something). We practiced using walaupun in concessive sentences.",
  "occurred_at": null
}
```

3. La respuesta 202 incluye `session_id`, `run_id` y `status_url`. Consultar `GET /v1/me/processing-runs/{run_id}` hasta `completed`. Un problema de clave, permisos del modelo o cuota se informa en `error_code`; la API no genera resultados ficticios. No es necesario mantener abierta la petición inicial.
4. Consultar `/v1/me/sessions/{session_id}/summary`, `/evidence`, y `/v1/me/languages/{track_id}/knowledge` o `/progress`.
5. Enviar otra clase, con otra key, usando el mismo track:

```json
{
  "title": "Clase de malayo 2",
  "text": "We reviewed walaupun. The student used it correctly without assistance. We also introduced meskipun as an alternative and practiced the difference between sempat and berpeluang."
}
```

Se espera que walaupun y sempat se reconozcan como revisitados, y meskipun y berpeluang como nuevos en el historial. El LLM puede producir construcciones adicionales; no se cuentan como lexemas. Los resultados de extracción son heurísticos y se deben revisar. Exposición a una palabra no la convierte en aprendida y un acierto reportado no certifica dominio.

Swagger muestra `X-Dev-User` opcional en las rutas privadas: vacío utiliza el UUID demo `00000000-0000-4000-8000-000000000001`. Otro UUID permite simular otra persona con su propio historial. **Esta cabecera no es autenticación**; cualquiera con acceso al servidor local podría escoger otra identidad. Los filtros de pertenencia, FKs y RLS aíslan los datos una vez seleccionada esa identidad, pero aún falta verificar quién la controla.

## Clases bilingües: idioma objetivo e idiomas puente

El track fija el idioma **objetivo** que se está aprendiendo. `bridge_languages` permite declarar los idiomas de las explicaciones y traducciones; admite hasta cinco tags, por ejemplo `es`, `en` o `pt-BR`. No tienen que ser idiomas habilitados como tracks. El objetivo no puede ser también puente, ni una variante de ese mismo idioma.

```json
{
  "title": "Malayo con explicaciones en español e inglés",
  "bridge_languages": ["es", "en"],
  "text": "dormir = tidur = sleep; kadang-kadang = a veces; sala de estar = living room"
}
```

Para un track `ms`, se deben registrar `tidur` y `kadang-kadang`, con sus citas originales completas. `dormir`, `sleep` y las otras traducciones no aportan conocimiento de esos idiomas. Una línea que solo contiene español/inglés se omite, sin inventarle una traducción al malayo. Mezclar idiomas no es motivo de advertencia por sí mismo. Las expresiones de varias palabras también pueden ser vocabulario; solo se extraen construcciones cuando hay un patrón gramatical explícitamente trabajado.

El campo es opcional: omitirlo o enviar `[]` habilita la interpretación automática de los idiomas puente. Esto conserva compatibilidad con clases anteriores. Las etiquetas son contexto para el LLM, no un filtro rígido: una traducción adicional en otro idioma no invalida la clase.

Cada run conserva su contexto y lo muestra en `/processing-runs/{id}`, en el resumen y en la procedencia de la evidencia. Para reprocesar una clase anterior con contexto explícito:

```json
{
  "expected_revision": 1,
  "bridge_languages": ["es", "en"]
}
```

En reprocess, omitir el campo o enviar `null` hereda el contexto de la revisión anterior; `[]` vuelve al modo automático. La sesión conserva los idiomas puente del envío original y los runs conservan los de cada reprocesamiento. Las correcciones reutilizan la extracción y el contexto de la publicación corregida. Cambiar contexto requiere otra Idempotency-Key.

## Correcciones, historial y reintentos

`POST /v1/me/sessions/{id}/corrections` admite descartar una observación o corregir correctness/assistance. Obtener `observation_id` de `/evidence`, usar `expected_revision` de la sesión y una key nueva. Ejemplo:

```json
{
  "expected_revision": 1,
  "observation_id": "copiar-uuid-de-evidence",
  "correctness": "incorrect",
  "reason": "La nota atribuía un acierto que no ocurrió"
}
```

Se genera otra revisión a partir de la extracción y las comparaciones guardadas, sin repetir esas llamadas. Una publicación anterior a `lexical-v3` puede necesitar su primera comparación contextual. Las observaciones anteriores permanecen en el historial, pero solo la publicación vigente contribuye al progreso. La revisión anterior sigue activa mientras se procesa la nueva.

`POST .../reprocess` con `{"expected_revision":2}` vuelve a extraer el texto original y conserva las correcciones ancladas por concepto/actividad/cita. Si un anclaje cambia, el nuevo run queda `needs_review` con `correction_anchor_changed` y no reemplaza la publicación anterior. En este MVP la reconciliación manual de anclajes cambiados requiere intervención de desarrollo; no hay un botón que ignore correcciones silenciosamente. No se permite editar el texto original de una sesión; un texto corregido se envía como otra clase por ahora.

Para aplicar una nueva política de reconciliación a la extracción publicada, enviar `{"expected_revision":1,"reuse_extraction":true}`. Se reutilizan texto extraído, modelo y procedencia de extracción; se generan comparaciones contextuales nuevas. No permite cambiar los idiomas puente al mismo tiempo, porque ese cambio requiere extraer de nuevo. Puede consumir una llamada de comparación a OpenAI aunque no se repita la extracción.

El reconciliador `lexical-v3` busca primero coincidencias del historial efectivo anterior a la clase, incluso si cambió el POS. Cuando hay cambios de categoría o glosas diferentes, compara candidatos del mismo idioma y lema con sus contextos mediante una salida estructurada de OpenAI. Un cambio de POS no basta para crear otra palabra, y la misma escritura no basta para fusionar homógrafos. Sin identidad respaldada se conserva un provisional marcado para revisión; no se fusionan globalmente los conceptos ni se reescribe evidencia histórica.

Las traducciones/paráfrasis compatibles no se tratan automáticamente como contradicciones. Una glosa conflictiva o incierta aparece en `summary.gloss_conflicts` y activa `review_required`. La evidencia conserva `observed_gloss`, `canonical_gloss`, la relación y el motivo en `provenance`; no se sobreescribe la glosa canónica con el apunte nuevo. `counts-v2` conserva el resultado reportado de un intento, pero no lo cuenta como acierto demostrado mientras su significado requiera revisión.

Las comparaciones se guardan en PostgreSQL antes de publicar: un retry de publicación no repite llamadas ya guardadas. Se comparan hasta 10 candidatos por item y 100 pares por run; superar el límite produce revisión explícita. Las decisiones del modelo son heurísticas auditables, no una validación lingüística certificada ni una comprobación exhaustiva de todas las traducciones. Una clase sin candidatos previos puede conservar una glosa errónea sin detectarla todavía.

Repetir una solicitud con la misma key y payload devuelve los mismos IDs; reutilizar la key con otro payload devuelve 409. Dos clases con texto idéntico y keys distintas son encuentros distintos. Los listados tienen `limit` y cursor `after` (último `id` recibido), en orden por UUID; las páginas de knowledge pueden cambiar después de publicar o reconstruir progreso.

Estados del run: `queued`, `running`, `retrying`, `completed`, `failed`, `superseded` o `needs_review`. Revisar `review_required` incluso en completed. Hasta tres intentos automáticos ante errores transitorios, con backoff; los errores de credenciales o citas inexistentes son terminales. Usar reprocess para iniciar otra revisión después de resolver un fallo.

## Desarrollo en el host

```sh
# Desde la raíz:
docker compose up -d db redis
cd apps/backend
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.lock
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn linguatrack.main:app --reload --host 127.0.0.1 --port 8001
```

En terminales separadas, desde `apps/backend`:

```sh
.venv/bin/dramatiq linguatrack.jobs --processes 1 --threads 2
```

```sh
.venv/bin/linguatrack dispatch
```

No ejecutar simultáneamente otra API sobre el puerto 8001. Si ya está en Compose, usar `docker compose stop api worker dispatcher` antes de correr estos procesos en el host.

## Diccionario de referencia

El backend funciona con conceptos provisionales privados aunque no se importe ningún diccionario. Para probar el contrato de importación con los fixtures sintéticos del repositorio, desde `apps/backend`:

```sh
.venv/bin/linguatrack import-reference ../../packages/lexicon/examples/output
```

Esto no descarga datos reales. El importador comprueba hashes, conteos, JSON Schema, procedencia, estado de fuentes y licencias; guarda manifest y atribución, admite `--allow-nc` explícito para fuentes NC revisadas y es idempotente por manifest. La transacción publica el build completo o ninguno. No implica permiso para redistribuir los datos importados.

Las assertions de todas las tablas se conservan. Solo las entradas lemma se enlazan a conceptos de vocabulario en este MVP. Sentidos, formas, morfología, relaciones, frecuencia y CEFR conservan su payload original sin inventar equivalencias. La resolución automática usa idioma exacto, NFC/casefold, tipo y POS; SCONJ/CCONJ comparten identidad léxica para tolerar variaciones de anotación, conservando el análisis original en cada evidencia. Una etiqueta de construcción que contiene solo una palabra con POS léxico se normaliza a lexema y se marca para revisión. Esto no transfiere dominio a funciones gramaticales. Referencias ambiguas producen un concepto privado revisable. Los conceptos públicos de fuentes distintas no se fusionan automáticamente. Una nueva snapshot con IDs de entrada diferentes puede necesitar alineación revisada: los UUIDs ya referenciados nunca se reasignan.

## Pruebas

Con PostgreSQL del Compose activo, desde `apps/backend`:

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests migrations
.venv/bin/ruff format --check src tests migrations
.venv/bin/alembic check
```

Las pruebas crean y eliminan una DB con nombre aleatorio, usan el rol real sin BYPASSRLS y no tocan las clases de desarrollo. OpenAI se sustituye por un extractor controlado: no consumen tokens ni necesitan una clave. Cubren replay, correcciones, reentregas, citas falsas, atribución al profesor, outbox, recuperación de lease, aislamiento e integridad del importador. `TEST_ADMIN_DATABASE_URL` permite indicar un PostgreSQL de pruebas con permisos de crear bases y roles.

Los modelos de extracción reales se validan mediante un smoke test separado y acotado; las pruebas deterministas no certifican precisión lingüística del LLM.

## Operación local y límites actuales

```sh
docker compose logs --tail=50 api worker dispatcher
docker compose stop
docker compose up -d
```

El dispatcher recupera runs pendientes y leases vencidos. Un token de lease impide que un worker antiguo publique después de ser reemplazado. No hay garantía de una única llamada al proveedor si se corta el proceso después de recibir la respuesta pero antes de guardarla. La proyección se reconstruye por track bajo lock; debe cambiarse a reconstrucción por conceptos afectados antes de tracks muy grandes.

Implementado: ingesta manual, OpenAI estructurado, usuario local, múltiples tracks, outbox y workers, evidencia con citas, progreso explicable, revisión/reproceso, importación conservadora y contratos de futuras fuentes. pgvector está instalado y hay almacenamiento reservado para embeddings de 1536 dimensiones; **no se ejecutan búsquedas semánticas ni llamadas de embeddings** sin evaluar el modelo.

Pendiente de etapas posteriores: autenticación OIDC, conectores reales Zoom/Meet/Duolingo/MCP, reconciliación de sentidos/homógrafos avanzada, formas como competencias independientes, embeddings evaluados, promoción de provisionales, correcciones de lemma/span, evaluaciones CEFR y modelos probabilísticos. El límite de texto por clase es 40.000 caracteres; no se trunca ni se implementa chunking todavía. No hay cuotas por usuario, retención automatizada, endpoint de borrado ni respaldos gestionados en este entorno local. Antes de exponerlo públicamente se necesita completar esas operaciones y autenticación.
