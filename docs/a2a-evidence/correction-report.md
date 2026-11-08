# Corrección R1/R2 — evidencia del implementador

**Resultado local: 478 pruebas pasan, 0 fallan; no es una segunda revisión independiente ni aceptación real.**

Checkout `/workspace/lfc/a2a-integration`, rama `feature/a2a-outbound-recovery`,
HEAD `1c8aaad2180bbf2fc34f097ab90d069170584ccd`. No commits, push, PR, despliegue,
cambios en `/opt/hermes`, configuración productiva, servicios ni llamadas al peer.
`independent-review.md` y las evidencias anteriores no se sobrescribieron.

## R1: propietario de escritura por solicitud

- `Client.send` y `Client.resume` adquieren un `flock` no bloqueante por identidad
  local durante la operación completa. Cada apertura tiene su descriptor propio:
  funciona entre threads y procesos, y el kernel libera la propiedad al morir.
- Un resume mientras otro escritor tiene el lock devuelve la última instantánea
  durable, sin GetTask ni escritura/revisión. Sin task ID también es solo lectura;
  conserva tanto prepared como uncertain o Message observado.
- La reclamación one-shot sigue en SQLite antes de la red. No se reintenta envío,
  no se ignoran errores de disco y CAS sigue rechazando escrituras obsoletas.
- Regresión loopback con barreras antes del ack, después del ack (seguido de
  input-required) y durante GetTask. El observador usa otro proceso CLI; luego
  otro CLI recupera los IDs mediante GetTask y un segundo send es rechazado.
  Los tests existentes que matan el cliente vuelven a pasar con el nuevo lock.
- Los archivos `.lock` no se borran: sustituir su inode permitiría dos propietarios.
  No hay transacción SQLite abierta durante el intercambio de red.

## R2: validar antes de mutar

- Validación recursiva de Message, Task, TaskStatus, StatusUpdate, ArtifactUpdate,
  Artifact y Part: campos requeridos, tipos, enums, IDs, historial, metadatos,
  flags, base64 y timestamp. GetTask atraviesa la misma validación de Task.
- La selección de la variante y la validación completa preceden cambios de
  correlación/estado. Se prepara una copia del registro, se verifica identidad,
  se guarda y solo entonces se actualiza el objeto del llamador. Rechazos no
  dejan mutaciones parciales en memoria ni en SQLite.
- Un Message `{}` o Task sin status produce ProtocolError, nunca observed.
  Pruebas loopback adicionales cubren las cuatro variantes malformadas como
  primer evento, seguidas de una supuesta finalización: no se certifica ni se reenvía.
- También se validan code/message/details de errores GetTask antes de persistir
  remote_missing. Los errores de streaming siempre abortan, sin incorporar datos.

### Fuente normativa y decisiones que evitan rechazo excesivo

Se consultaron:

1. <https://a2a-protocol.org/v1.0.0/specification/>, §§4.1–4.2, 5.5–5.6 y 9.5.
2. Proto del tag v1.0.0 fijado al commit
   `173695755607e884aa9acf8ce4feed90e32727a1`:
   <https://github.com/a2aproject/A2A/blob/173695755607e884aa9acf8ce4feed90e32727a1/specification/a2a.proto>.
   Copia exacta: `correction-a2a-v1.0.0.proto`;
   SHA256 `4b74c0baa923ae0acb55474e548f1d6e5d3f83b80d757b65f8bf3e99a3c2257f`.
3. <https://protobuf.dev/programming-guides/json/>: reglas de lectura de enums,
   aliases, null, bytes y Timestamp.

Las rutas supuestas `specification/json/a2a.json` y `spec/a2a.proto` devolvieron
404. Se descubrió `specification/a2a.proto` mediante el árbol GitHub del tag;
no se inventó un schema ni se añadió una dependencia al SDK.

- **Task.contextId es opcional** (proto L173); no se rechaza su ausencia pese a la
  sugerencia del informe previo. El ID de tarea y status sí son obligatorios.
- Los dos updates requieren contextId (L300/L312). No existe un campo `final`
  requerido en StatusUpdate 1.0.
- La prosa normativa de Message (L254–259) requiere contexto para mensajes de
  servidor. Se corrigió el fixture previo de Message ROLE_AGENT añadiendo
  contextId, sin eliminar su prueba de persistencia/resume sin task ID.
  El primer intento GREEN dejó visible esa única discrepancia del fixture.
- Message.parts es array requerido pero sin mínimo declarado; Artifact.parts
  requiere al menos una parte. No se exige UUID a IDs de ejemplo válidos.
- Part.data admite objeto, array, escalar y null; Part contiene exactamente una
  variante. Se admite base64 estándar/URL-safe con o sin padding.
- Lectura acepta aliases snake_case y enums enteros conocidos, como ProtoJSON;
  el evento original se conserva sin reescritura. `remote_state` utiliza el
  nombre semántico del enum para clasificar estados. Se rechazan aliases
  duplicados y valores de enum desconocidos; no se convierten booleans en ints.
- Null opcional significa campo no establecido; required ausente/null falla.
  Campos de extensión desconocidos se conservan como datos, sin ejecutarlos.

## TDD y comandos ejecutados

Runner canónico, `.venv` existente, entorno limpio, sin instalación de paquetes.
Todas las ejecuciones usan `--file-retries 0` para no ocultar fallos por reintento.
Los logs contienen salida real completa.

| Evidencia | Resultado |
|---|---|
| `correction-r1-red.txt` | 4 fallos: revisión pre-ack, escritura post-ack, GetTask concurrente y consumo de prepared |
| `correction-r1-green.txt` | 54 pasan |
| `correction-r2-red.txt` | 79 fallan / 30 pasan; `{}` y Task sin status no lanzaban error |
| `correction-r2-first-green.txt` | 162 pasan / 1 falla: fixture antiguo Message servidor sin contexto |
| `correction-r2-green.txt` | 163 pasan tras corregir ese fixture conforme al proto |
| `correction-protojson-red.txt` | 9 fallan: 6 formas válidas de lectura y 3 errores GetTask malformados |
| `correction-protojson-green.txt` | 118 pasan |
| `correction-final-suite.txt` | 11 archivos, 478 pasan, 0 fallan, 19.3 s |
| `correction-verification-final.txt` | Ruff y whitespace sin diagnósticos; total sumado por programa |

Comandos (desde el checkout):

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py -k 'concurrent_resume_is_read_only or resume_prepared' --file-retries 0
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py --file-retries 0
scripts/run_tests.sh tests/plugins/test_a2a_outbound_validation.py --file-retries 0 --tb=short
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py --file-retries 0 --tb=short
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py --file-retries 0
scripts/run_tests.sh tests/plugins/test_a2a_outbound_validation.py -k 'protojson_read or error_validated' --file-retries 0 --tb=short
scripts/run_tests.sh tests/plugins/test_a2a_outbound_validation.py --file-retries 0
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py --file-retries 0
.venv/bin/python -m ruff check plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
git diff --check
# Para cada archivo nuevo/no rastreado de código/tests/runbook:
git diff --no-index --check /dev/null RUTA
```

El primer script de verificación interpretó erróneamente el exit 1 de
`git diff --no-index --check` como fallo; ese código refleja que el archivo
nuevo difiere de `/dev/null`. `correction-verification.txt` conserva ese error
del verificador. La ejecución final comprueba también stdout/stderr vacíos:
no hubo errores de whitespace. No se atribuye ese fallo a la implementación.

Conteo comprobado por Python: 58 outbound recovery + 118 validation + 162 A2A
existentes + 140 aprobaciones = 478. Incluye los 352 casos anteriores y 126
nuevos; no es toda la suite general de Hermes, sino todos los archivos del
conjunto acordado de 352 más los nuevos.

## Archivos de entrega

Modificados respecto al trabajo anterior sin commit:

- `plugins/platforms/a2a/outbound.py`
- `tests/plugins/test_a2a_outbound_recovery.py`
- `docs/a2a-outbound-runbook.md` (solo cambios de comportamiento documentados)

Nuevos:

- `tests/plugins/test_a2a_outbound_validation.py`
- `docs/a2a-evidence/correction-*.txt`, fuente `.proto`, este informe y manifiesto
  `correction-manifest.json`.

El fixture `tests/plugins/fixtures/a2a_outbound_peer.py` no se modificó.
Se registraron las lecciones reutilizables en la memoria procedimental
`hermes-source-fork-integration/references/a2a-private-integration.md` del perfil
activo; no se modificó código ejecutable, configuración ni servicios del runtime.

## Límites / puertas que siguen pendientes

- Segunda revisión independiente obligatoria. Este informe pertenece al implementador;
  no sustituye `independent-review.md` ni cambia su veredicto histórico.
- Carlos debe recibir y decidir personalmente approve/deny; no se implementó ni
  acreditó el puente remoto de aprobación. codex-a2a real sigue sin aceptación.
- Fixtures loopback propios, no Codex. Las respuestas GetTask simuladas no prueban
  supervivencia de la ejecución remota real ni autorizaron llamadas privadas.
- Linux/POSIX y disco local privado; no se probó NFS, pérdida física de energía ni
  endurecimiento adicional de dueño/permisos de una BD preexistente (observación
  previa fuera de R1/R2). No borrar locks ni mezclar procesos del cliente viejo
  sin lock con el corregido; CAS sigue fallando cerrado si otro escritor ajeno
  al API intenta intervenir.
- No se habilitan tool nativo, inbound, cron, callbacks ni reenvío automático.
  Despliegue y arranque siguen requiriendo revisión y autorización separadas.
