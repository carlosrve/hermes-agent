# Revisión independiente A2A outbound

**Veredicto: `passed: false`. No aprobar publicación como código verificado ni activación.**

Alcance: los cuatro archivos nuevos solicitados, README de evidencia, resultado final y manifiesto. Rama comprobada `feature/a2a-outbound-recovery`; HEAD/base `1c8aaad2180bbf2fc34f097ab90d069170584ccd`. Revisión independiente, sin cambios de implementación, commits, push, despliegue, interacción humana ni llamadas al peer privado. Única escritura deliberada de entrega: este informe. Los tests usan almacenamiento temporal y loopback.

## Hallazgos bloqueantes

### R1 — Alta: `resume` concurrente puede impedir persistir el primer reconocimiento remoto

**Ubicación:** `plugins/platforms/a2a/outbound.py:255-263`, `340-354`, `356-370`; efecto en `219-241`.

Después de `claim_send`, el emisor conserva la revisión N y espera su primer evento. Otra instancia ejecuta `resume` antes del reconocimiento: como aún no hay `task_id`, vuelve a guardar `uncertain`, incrementando la revisión aunque no aporta información. Cuando llega el primer task/context válido, el emisor intenta guardarlo con N y falla por CAS. La BD permanece sin identificación remota; siguientes `resume` no pueden hacer GetTask. No hay envío duplicado, pero se pierde precisamente la correlación necesaria para recuperar una tarea que sí fue reconocida.

Reproducción determinista sin red, usando Store/Client reales en directorio temporal: `prepare → claim_send → resume → _event(task working con id/context)`. Resultado ejecutado:

```text
concurrent_resume_ack: Concurrent update; reload before explicit recovery durable_task_id= None
```

**Arreglo mínimo:** no escribir en la rama sin task ID cuando el estado ya es `uncertain`; preservar también `prepared` sin consumirlo mediante una operación de consulta. Definir cómo se coordinan `send` activo y recuperaciones concurrentes: una recuperación no debe invalidar la persistencia del primer ack. Añadir test con dos clientes y barrera antes del ack, seguido de reinicio y GetTask. No resolverlo ignorando errores de persistencia ni reintentando SendStreamingMessage.

### R2 — Alta: un Message inválido se acepta como resultado final durable

**Ubicación:** `plugins/platforms/a2a/outbound.py:212-241`, `247-250`, `258-260`; cobertura insuficiente en `tests/plugins/test_a2a_outbound_recovery.py:328-352`.

La validación comprueba que `message` sea dict, pero no valida su estructura mínima. Un JSON-RPC correlacionado con `result: {"message": {}}` se guarda con `local_state=observed`, interrumpe el stream y queda definitivamente observado en `resume` sin task ID. No contiene identidad de mensaje, role ni partes de respuesta; no debería certificar una observación final válida. Esto puede descartar un task posterior del stream y dejar una solicitud real sin recuperación. También se acepta un Task con id/context pero sin status; demuestra que no se está validando el contrato del tipo antes de incorporarlo al estado.

Reproducción ejecutada sin red con `_event` real:

```text
empty_message: observed
task_without_status: None
```

**Arreglo mínimo:** validar campos obligatorios, tipos y valores admitidos por cada variante A2A 1.0 antes de modificar el registro: Message (identidad, rol y partes), Task (identidad/contexto/status), statusUpdate y artifactUpdate. No marcar `observed` por la sola presencia de una clave `message`. Añadir tests de Message vacío/malformado, Task sin status/contexto, IDs inválidos y preservación del último estado durable ante rechazo. Mantener fail-closed: error de protocolo, nunca éxito terminal ni reenvío.

## Evaluación del resto del contrato

- **Intención antes de red:** `prepare` confirma SQLite y fsync de directorio; `claim_send` usa `BEGIN IMMEDIATE`, cambia a incierto y confirma/fsync antes de conectar. Hay prueba multiproceso de reclamación única y prueba de fsync fallido sin petición. Es un buen fundamento de envío único por identidad local; no es deduplicación global de encargos nuevos.
- **Correlación inmediata:** el generador entrega cada evento y el consumidor guarda antes de pedir el siguiente. El test que mata el cliente tras observar IDs mientras el stream sigue vivo lo comprueba. R1 rompe esta propiedad bajo concurrencia legítima. Los errores de disco se propagan, sin fingir persistencia.
- **Recuperación:** exclusivamente GetTask con ID conocido; sin ID no se reenvía. `remote_missing` conserva el estado remoto anterior. Los estados working e intervención están separados; input/auth detienen el stream sin contestar automáticamente. Se conserva el contenido de eventos/artefactos, incluidos flags, sin ejecutar datos ni descargar URIs.
- **Wire:** JSON-RPC **2.0 sobre A2A 1.0**, no JSON-RPC 1.0. Métodos y envolturas documentados coherentemente. Se comprueban correlación, media type, límites de lectura, delimitadores SSE, UTF-8, claves duplicadas y profundidad. Los errores RPC abortan; falta la validación por variante de R2. EOF después de un evento working devuelve observación incierta, no tarea completada.
- **Transporte/secretos:** endpoint literal restringido, TLS de sistema, sin proxies de entorno ni redirects, no AgentCard fetch, bearer obligatorio por variable y no headers en BD. HTTP únicamente por opt-in loopback. No observé shell injection, SQL interpolado, eval, pickle ni secretos reales en los archivos revisados. No equivale a certificar identidad Codex ni resolución Tailscale: el runbook exige comprobarlo y advierte que el hostname corto puede no servir para el endpoint real.
- **Almacenamiento:** disco local/POSIX, SQLite FULL, CAS, propagación de errores; no se probó pérdida de energía real. La BD nueva se crea 0600. Como endurecimiento adicional, validar dueño/permisos/tipo de una BD ya existente; actualmente solo se verifica privacidad del directorio y se rechaza symlink al abrir el destino inicialmente (`301-309`).

## Tests, evidencia y límites

Ejecución independiente:

```text
python -m pytest ... → /usr/local/bin/python: No module named pytest
.venv/bin/python -m pytest -q -p no:cacheprovider tests/plugins/test_a2a_outbound_recovery.py
.................................................. [100%]
50 passed in 13.23s
```

No se instaló nada ni se alteró el runtime. Los dos defectos anteriores se reprodujeron adicionalmente mediante llamadas reales al módulo con BD temporal; no forman parte de esos 50 casos y no contradicen que la suite existente pase.

Se leyó `28-final-suite.txt` y se sumaron sus resultados por archivo en Python: outbound 50, A2A existente 162, aprobaciones 140, total 352. Esta revisión **no volvió a ejecutar** las otras suites: son evidencia registrada del implementador, no ejecución independiente. Los SHA256 de los cinco archivos del manifiesto coinciden con los archivos revisados.

Los fixtures son expresamente propios, no codex-a2a. `test_separate_client_and_server_restart_never_resends` cambia ambos procesos; `test_client_killed_after_ack_recovers_from_durable_ids` mata realmente al cliente; `test_server_disconnect_during_execution_keeps_working` mata al servidor con cliente aún vivo. Están diferenciados honestamente. Como mejora de cobertura, aislar también reinicio de cliente con servidor intacto y corte del cliente antes del ack: el modo before-ack actual corta desde servidor. El fixture transforma working en completed al responder GetTask (`fixtures/a2a_outbound_peer.py:71-75`); no demuestra supervivencia de ejecución real de Codex ni aprobación humana. El README y runbook no lo presentan como tal.

## Alcance funcional y aceptación humana

La CLI es utilizable como primera fase manual y está descrita con precisión (`docs/a2a-outbound-runbook.md:15-25,102-141`): stdlib, prepare/show/send/resume, sin tool registrado, cron, inbound ni activación automática. No es una integración nativa completa de Rafa. Esto es una limitación declarada, no una falsa entrega de tool.

**Aceptación del objetivo completo sigue bloqueada**, aun corrigiendo R1/R2. No hay puente remoto input-required → solicitud a Carlos → decisión correlacionada → continuación de Codex (`runbook:162-167`). La superficie real de zuri puede servir como mecanismo humano, pero debe probarse coordinadamente; no se puede inferir de esta implementación. Las 140 pruebas de aprobación local no demuestran recepción por Carlos ni approve/deny remoto.

Antes del uso real: revisión/MR y aprobación de inicio separada; URL/TLS/bearer/AgentCard/runtime y ruta privada Tailscale verificados; encargo inocuo, cortes/reinicios/GetTask; recepción humana real con correlaciones, aprobación que habilita efecto una sola vez, denegación sin efecto, y ausencia de respuesta/auth-required que permanece bloqueada. Todas esas puertas continúan pendientes; esta revisión no autoriza ninguna llamada privada ni activación.

## Recomendación

Corregir únicamente R1/R2 y añadir regresiones negativas/concurrentes; repetir revisión independiente. Se puede evaluar luego una MR experimental como fase CLI explícita, manteniendo prohibición de despliegue y aceptación E2E pendiente. No declarar solucionado el objetivo Rafa → Zuri/Codex ni aprobación real de Carlos basándose en fixtures verdes.
