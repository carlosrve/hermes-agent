# Tercera revisión independiente — A2A outbound

**Veredicto: `passed: true` exclusivamente para el fundamento CLI manual opt-in revisado. No encontré bloqueantes reproducibles pendientes en ese alcance. R3 y R4 corregidos; R1/R2 conservan sus garantías probadas.**

**NO acredita integración nativa completa, aceptación de codex-a2a real de Zuri, recepción/approve/deny de Carlos, despliegue ni autorización de arranque.** Esas puertas siguen pendientes.

## Identidad y método

- Checkout `/workspace/lfc/a2a-integration`, rama `feature/a2a-outbound-recovery`, HEAD/base `1c8aaad2180bbf2fc34f097ab90d069170584ccd` comprobados con Git.
- Implementación/tests/runbook siguen sin seguimiento. Un diff rastreado vacío no demuestra ausencia de código. Se leyeron completos `outbound.py`, ambos tests outbound, fixture, runbook, `independent-review.md`, `second-independent-review.md`, `correction-report.md` y `correction-r3-r4.md`.
- SHA256 ejecutado de `outbound.py`: `6efca80535214c90769af2828ef411f0fef6fe0b58ae7545bafc1997601376f0`.
- Se cargaron requesting-code-review y hermes-source-fork-integration, incluida su referencia A2A. La instrucción de solo revisión excluye arreglos, commits y despliegue del flujo general.
- Sin cambios de implementación, instalaciones, commits, push, PR, llamadas a peers reales, ni modificaciones del runtime. Única escritura deliberada de entrega: este informe. El runner autorizado produce sus cachés habituales de bytecode, pytest y duraciones; las pruebas usan BD temporales y fixtures loopback. Git no muestra cambios rastreados después de ejecutarlo.

## Fuente normativa verificada independientemente

Se descargó **en memoria**, sin credenciales, el proto oficial fijado:

<https://raw.githubusercontent.com/a2aproject/A2A/173695755607e884aa9acf8ce4feed90e32727a1/specification/a2a.proto>

Coincide byte por byte con `correction-a2a-v1.0.0.proto`; SHA256 calculado `4b74c0baa923ae0acb55474e548f1d6e5d3f83b80d757b65f8bf3e99a3c2257f`.

- Líneas 244–259: ROLE_USER/1 es cliente→servidor; ROLE_AGENT/2 es servidor→cliente; Message del servidor requiere contexto.
- Líneas 775–781: StreamResponse.message es explícitamente un mensaje **del agente**.
- Líneas 167–180 y 210–218: Task.history contiene las interacciones y TaskStatus.message es un mensaje asociado; no se impone allí indiscriminadamente rol agente.
- Task.contextId es opcional en el proto (173). Part.data es google.protobuf.Value (232–233), no exclusivamente objeto; las cadenas `NaN`/`Infinity` no son números no finitos.

## Correcciones confirmadas

### R3 — Cerrado

`outbound.py:119–121` exige contexto no vacío a ROLE_AGENT, también después de normalizar enum entero y aliases. `:340–361` valida el envelope y variante completa y exige rol agente **en la posición StreamResponse.message**, antes de crear el candidato o persistir. ROLE_USER/ROLE_UNSPECIFIED/0/1 no pueden certificar una respuesta final ni cortar el stream como éxito.

La restricción no invade Task.history ni los mensajes asociados al status. Los positivos ejecutados aceptan ROLE_USER/1 sin contexto y ROLE_AGENT/2 con contexto. No se reinterpretan claves role dentro de Part.data.

Reproducción independiente de la secuencia defectuosa antigua mediante `Client.send`/`resume`, `_open` sustituido por BytesIO y SQLite temporal real: cuatro roles inválidos, cada uno seguido de un Task válido. Ahora los cuatro producen ProtocolError; conservan uncertain sin IDs/eventos, resume no hace red y un segundo send se rechaza. No se pretende rescatar el Task posterior a un protocolo malformado: abortar y conciliar es el comportamiento fail-closed declarado.

### R4 — Cerrado

`outbound.py:134–156,159–192` verifica finitud y tipos JSON recursivamente después del decoder. `:340–341` repite esa defensa para entradas nativas antes de mutar correlación/estado. Se inspecciona todo el envelope, incluidos metadata, extensiones y errores GetTask; un -32001 con contenido no finito no alcanza remote_missing.

`allow_nan=False` está explícito en petición HTTP (306), comprobación de eco (342), insert/claim/save durable (508/531/537) y salida CLI (572). No sustituye la validación previa. Store.save serializa antes de modificar SQLite o incrementar la revisión del llamador.

La reproducción independiente confirmó rechazo de `1e999`, `-1e999`, `NaN`, `Infinity`, `-Infinity`, y de NaN/±inf nativos anidados, preservando exactamente memoria y BD tras un ack. La suite incluye ambas rutas SSE/GetTask, datos anidados, artefactos, historial, metadata, extensiones y errores, además de positivos finitos/cadenas especiales.

## Riesgos altos restantes examinados

| Área | Resultado dentro del alcance CLI |
|---|---|
| Escritores concurrentes | send/resume mantienen flock por solicitud durante toda la operación (`384–408,476–497`); el observador sin lock carga sin guardar ni hacer GetTask. CAS sigue como segunda defensa. Pasaron barreras multiproceso pre-ack/post-ack/durante GetTask y consulta prepared. No encontré otra pérdida de ack reproducible bajo API pública, disco privado POSIX y procesos corregidos. |
| Barrera antes de envío | claim_send usa BEGIN IMMEDIATE y guarda uncertain antes de conectar (`519–533`). Un fallo fsync impide iniciar red aunque el commit ya pudiera existir. Nunca vuelve automáticamente a prepared. |
| Ack temprano y caída | `_event` guarda el candidato antes de actualizar memoria y antes de consumir el siguiente evento (`362–382,394–397`). Pasaron muerte real del cliente después de ver IDs durables mientras seguía vivo el stream, caída del servidor durante working y recuperación con procesos nuevos. No se promete supervivencia a pérdida física de energía. |
| Sin reenvío incierto | resume únicamente GetTask con task ID; sin ID solo observa. Segundo send se rechaza. Pérdida del task store produce remote_missing sin borrar IDs/último estado remoto. Crear otra identidad con prepare sigue siendo otro encargo, no recuperación. |
| SSE/JSON-RPC | JSON-RPC 2.0 sobre A2A 1.0, métodos y envolturas explícitos. Correlación, oneof, validación completa, aliases, enums, UTF-8, delimitación CR/LF/CRLF/BOM, límites, truncamiento y deadline revisados y pruebas verdes. Sin reconexión automática ni consumo de una variante final inválida. No se afirma conformidad exhaustiva de todo A2A fuera de estas rutas. |
| Intervención humana | input-required/auth-required se conservan y cierran el stream sin responder por Carlos. Una consulta GetTask explícita puede observar progreso remoto; no autoriza ni envía decisión humana. No se alteran aprobaciones, YOLO, gateway ni callbacks. |
| Secretos y transporte | Token obligatorio resuelto desde env; binding exacto del peer/endpoint; HTTPS con TLS del sistema, HTTP solo fixture loopback opt-in. HTTP != 200 aborta, no sigue redirect. Sin proxies de entorno, AgentCard fetch, ejecución/descarga de URIs, SQL interpolado o shell/eval/pickle en el módulo. Pruebas de redirect, binding, ausencia de token y eco pasan. No es detector universal de secretos. |

### Observaciones defensivas, no nuevos bloqueantes

- Store.load/claim leen JSON durable con json.loads ordinario. Una BD artificialmente contaminada de una versión antigua no se sanea ni migra; las nuevas serializaciones fallan ante no finitos. **No existe una BD desplegada de este módulo nuevo según el contexto autorizado**: no se presupone corrupción real ni se convierte una migración hipotética en requisito de esta fase.
- Dueño/permisos/tipo de una BD preexistente admiten endurecimiento adicional; directorio privado, archivo nuevo 0600 y rechazo inicial de symlink sí están implementados. No se demostró explotación bajo el directorio privado/usuario confiable declarado.
- El fixture convierte working en completed al consultar GetTask. No demuestra continuidad de ejecución real de Codex. Aislar adicionalmente muerte pre-ack del cliente o reinicio exclusivamente del cliente con servidor intacto ampliaría cobertura, pero no demuestra hoy un defecto bloqueante.
- El runbook enlaza main para una referencia wire general, pero la implementación y evidencia fijan el proto oficial y esta revisión cotejó esa fuente exacta. No se confundió documentación móvil con prueba del contrato revisado.

## Ejecución independiente

Desde `/workspace/lfc/a2a-integration`, `.venv` existente, sin instalaciones, runner canónico y sin reintentos por archivo:

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py --file-retries 0
```

Salida real, exit 0:

```text
=== Summary: 11 files, 579 tests passed, 0 failed (100% complete) in 19.2s (24 workers) ===
```

| Archivo | Pasan |
|---|---:|
| tests/plugins/test_a2a_outbound_recovery.py | 58 |
| tests/plugins/test_a2a_outbound_validation.py | 219 |
| tests/plugins/test_a2a_plugin.py | 105 |
| tests/plugins/test_a2a_phase23.py | 45 |
| tests/plugins/test_a2a_schema_registration.py | 1 |
| tests/plugins/test_a2a_tools_gate.py | 6 |
| tests/tools/test_a2a_reason_roundtrip.py | 5 |
| tests/tools/test_approval.py | 134 |
| tests/tools/test_approval_interrupt.py | 2 |
| tests/tools/test_approval_config_readonly.py | 3 |
| tests/gateway/test_approvals_command.py | 1 |
| **Suma comprobada en Python** | **579** |

El estimado inicial ~344 no es el conteo parametrizado. **579 corresponde a la selección A2A/aprobaciones, no a toda la suite Hermes.**

Sondas independientes adicionales ejecutadas con `.venv/bin/python -B -c`, sin archivo de test nuevo ni red, usando Client/Store reales, contextmanager BytesIO y TemporaryDirectory:

```text
R3 invalid-role stream cases: 4 rejected; no resend
R3 user history without context: accepted
R4 wire numbers: 5 rejected; memory and DB preserved
R4 native numbers: 3 rejected; memory and DB preserved
R3 agent missing/empty context: 2 rejected
R4 Store.save defense: rejected; revision and DB preserved
```

Exit 0. Estas sondas no se suman a los 579 tests de pytest. Un primer lanzamiento del script de sondas falló por escape de salto de línea en el propio comando (`SyntaxError: unterminated string literal`); se corrigió el comando en memoria y se volvió a ejecutar satisfactoriamente. No fue un fallo del producto ni requirió editar código.

```bash
.venv/bin/python -m ruff check --no-cache plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
# All checks passed!, exit 0
git diff --check
# sin diagnósticos; solo cubre diff rastreado
```

## Conclusión y puertas pendientes

No reproduje nuevos bloqueantes de corrección/seguridad del fundamento CLI revisado. Los ejemplos R3/R4 anteriores ya no se aceptan y sus regresiones no sacrifican los historiales user válidos. La revisión puede acompañar la evaluación/publicación por el flujo autorizado; no publica ni activa nada por sí misma.

**Integración nativa, puente de aprobación y aceptación real siguen incompletos:** Carlos debe recibir y resolver personalmente casos approve/deny correlacionados; deben verificarse efectos y continuación con codex-a2a real de Zuri, identidad/URL/TLS/red privada, persistencia y cortes reales. Las pruebas locales de aprobaciones no acreditan ese recorrido. Despliegue/inicio requieren autorización separada; no habilitar inbound, puertos públicos, cron, callbacks ni jobs automáticos.
