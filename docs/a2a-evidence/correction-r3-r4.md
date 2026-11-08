# Corrección aislada R3/R4 — pendiente revisión independiente

## Resultado y alcance

Implementación corregida con ciclos RED→GREEN separados. Rama exclusiva `feature/a2a-outbound-recovery`, checkout `/workspace/lfc/a2a-integration`, HEAD sin cambios `1c8aaad2180bbf2fc34f097ab90d069170584ccd`. No commits, push, PR, instalación de dependencias, cambios de runtime/configuración/servicios ni llamadas a peers reales. Se usó `.venv` existente. Las pruebas canónicas abren los fixtures loopback ya existentes; las nuevas usan bytes en memoria y SQLite real temporal.

Se modificaron únicamente `plugins/platforms/a2a/outbound.py` y `tests/plugins/test_a2a_outbound_validation.py`, y se agregaron este informe y logs `correction-r3-r4-*.log`. Los archivos de revisión independiente permanecen intactos. La implementación y pruebas ya eran archivos no rastreados: `git diff --check` por sí solo no inspecciona su contenido.

## R3: semántica por posición, no restricción indiscriminada

Referencia normativa local: `correction-a2a-v1.0.0.proto`, fijada a A2A v1.0.0, commit `173695755607e884aa9acf8ce4feed90e32727a1`; SHA256 comprobado `4b74c0baa923ae0acb55474e548f1d6e5d3f83b80d757b65f8bf3e99a3c2257f`. No se descargó nuevamente la fuente oficial.

- `StreamResponse.message` (:775–781): explícitamente mensaje **del agente**. Tras normalizar enum/aliases se exige `ROLE_AGENT` (también representación 2); la validación existente exige contexto no vacío a mensajes de servidor (:244–259). Se rechazan ROLE_USER/ROLE_UNSPECIFIED/0/1 antes de copiar o persistir el candidato.
- `StreamResponse.task` y resultado `GetTask`: objetos Task, no mensajes de respuesta final. Mantienen su validación completa de status/IDs/artifacts/history.
- `Task.history`: colección de mensajes de ambas direcciones. Conserva ROLE_USER/1 sin contexto y ROLE_AGENT/2 con contexto. No se convierte en una colección de respuestas de servidor.
- `Task.status.message` y `statusUpdate.status.message`: TaskStatus (:210–218) dice «message associated with the status», no «message from the agent». Se preserva el validador de Message y su contexto condicional por remitente; no se inventa una prohibición adicional de ROLE_USER. Hay positivos explícitos para ambas direcciones.
- `artifactUpdate.artifact`, `Task.artifacts` y Part.data: artefactos/datos, no posiciones Message; no se buscan ni reinterpretan claves `role` arbitrarias.
- `SendMessageResponse.message` (:763–771) tiene la misma semántica agente pero este cliente no implementa SendMessage. No se añade una ruta nueva.

Regresión real de `Client.send`: mensaje user/unspecified seguido de Task ya no se certifica `observed`. Se aborta con ProtocolError, sin consumir ni confiar en el Task posterior. Sin ack previo, conserva `uncertain`, sin IDs y sin eventos; `resume` no reenvía. No se pretende recuperar IDs nunca aceptados: continuar un stream malformado no forma parte del contrato. Con ack previo, la validación preserva exactamente memoria y registro durable.

## R4: números finitos antes de mutar

`_wire_json` aplica validación JSON recursiva inmediatamente tras decodificar, además de rechazar constantes explícitas y claves duplicadas. Rechaza overflow ±1e999 convertido por Python en infinito. El mismo control al inicio de `_event` cubre envelopes nativos con NaN/±inf, antes de comprobar credenciales, correlación, IDs o estado.

La inspección cubre TODO el envelope: partes/data, metadatos, artefactos, historial, extensiones y detalles de errores JSON-RPC. Por ello `GetTask` error -32001 con dato no finito no llega a mutar `remote_missing`. SSE y GetTask comparten el decoder. Límites de anidación también se aplican a objetos nativos.

Serialización defensiva `allow_nan=False` en solicitudes, detección de eco, insert/claim/save durable y salida CLI. No sustituye el rechazo anterior a mutación. `Store.save` se prueba directamente: rechaza NaN sin cambiar la revisión ni SQLite.

Part.data es `google.protobuf.Value` y metadata es `Struct` (:224–236,271–272,289–290). No hay campos float/double tipados consumidos por estas rutas. Las cadenas `"NaN"`, `"Infinity"`, `"-Infinity"`, `"1e999"` permanecen cadenas legítimas, no números; tampoco se vetan cadenas especiales en extensiones ProtoJSON. No se agregan coerciones numéricas ni un esquema especulativo para extensiones. Los positivos incluyen números finitos grandes, ceros, booleanos y null.

## TDD y comandos exactos

Directorio de todos los comandos: `/workspace/lfc/a2a-integration`. Logs completos adjuntos; las redirecciones solo capturan stdout/stderr. Los comandos RED de pytest devolvieron fallos esperados `DID NOT RAISE` (el shell de captura finalizaba con el comando que imprimía el log, por eso su exit global era 0).

```bash
.venv/bin/python -m pytest tests/plugins/test_a2a_outbound_validation.py -q -o addopts='' -k 'server_message_role or user_message_followed'
# correction-r3-r4-red-r3.log: 20 failed, 118 deselected

.venv/bin/python -m pytest tests/plugins/test_a2a_outbound_validation.py -q -o addopts=''
# correction-r3-r4-green-r3.log: 138 passed

.venv/bin/python -m pytest tests/plugins/test_a2a_outbound_validation.py -q -o addopts='' -k 'nonfinite or associated_messages'
# correction-r3-r4-red-r4.log: 35 failed, 46 passed, 138 deselected
# Constantes ya rechazadas y positivos legítimos pasan antes del cambio.

.venv/bin/python -m pytest tests/plugins/test_a2a_outbound_validation.py -q -o addopts=''
# correction-r3-r4-green-r4.log: 219 passed

scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py --file-retries 0
# correction-r3-r4-canonical.log: exit 0, 11 files, 579 tests passed,
# 0 failed (100% complete) in 19.2s (24 workers)

.venv/bin/python -m ruff check --no-cache plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
# All checks passed!, exit 0

git diff --check
# sin diagnósticos, exit 0
```

Conteos canónicos por archivo: recovery 58, validation 219, plugin 105, phase23 45, schema_registration 1, tools_gate 6, reason_roundtrip 5, approval 134, approval_interrupt 2, approval_config_readonly 3, approvals_command 1. Suma programática comprobada: **579**. Es toda la selección A2A/aprobaciones acordada, **no toda la suite de Hermes**. Sin reintentos de archivos. Se preservan las regresiones de flock, muerte de procesos, durabilidad inmediata y ausencia de reenvío incierto.

También se ejecutó `git diff --no-index --check /dev/null ARCHIVO` para `plugins/platforms/a2a/outbound.py`, `tests/plugins/test_a2a_outbound_validation.py` y este informe: los tres sin diagnósticos, exit 1 por ser archivos nuevos (verificación agregada exit 0).

## Límites y siguiente puerta

No se migra ni repara una BD previamente contaminada: las nuevas escrituras/salida no serializan NaN/Infinity; datos históricos corruptos requieren inspección explícita. No se cambia el endurecimiento pendiente de una BD preexistente, ni se promete rollback de fsync posterior a commit.

Sigue siendo CLI manual opt-in, no tool nativo. Puente Carlos approve/deny real, recepción/correlación humana y aceptación de codex-a2a real de Zuri siguen pendientes; mocks no los acreditan. Sin inbound nuevo, puertos públicos, cron, callbacks ni jobs. Se detiene para revisión independiente; suite verde no autoriza publicación, despliegue ni arranque.

Lección reutilizable para futuras correcciones: separar validación estructural de semántica por posición; validar finitud del árbol JSON completo tanto después del decoder como en entradas nativas, antes de cualquier mutación. No se modifica la biblioteca de skills fuera del checkout autorizado.
