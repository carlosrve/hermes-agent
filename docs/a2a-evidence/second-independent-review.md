# Segunda revisión independiente — A2A outbound

**Veredicto: `passed: false`.** R1 está corregido en la API pública; los dos ejemplos originales de R2 ahora se rechazan, pero quedan dos defectos reproducidos de validación. No aprobar el código como verificado ni activar el peer.

## Alcance e identidad

- Checkout `/workspace/lfc/a2a-integration`, rama `feature/a2a-outbound-recovery`, HEAD/base `1c8aaad2180bbf2fc34f097ab90d069170584ccd`.
- Los archivos nuevos siguen sin seguimiento; `git diff BASE` vacío no significa ausencia de implementación. Se leyeron completos `outbound.py`, ambos archivos de tests outbound, el fixture, runbook, revisión anterior y correction-report. Se contrastó el proto local fijado.
- SHA256 de `outbound.py`: `b05044cb9f6d6ad86d85d911b4140e478cb57e8645483c5ab949a666e245644d`.
- SHA256 del proto: `4b74c0baa923ae0acb55474e548f1d6e5d3f83b80d757b65f8bf3e99a3c2257f`, coincide con correction-report. Es contraste contra la copia local; esta revisión no descargó de nuevo la fuente oficial.
- Revisión sin cambios de implementación, dependencias, commits, push, PR, runtime, configuración ni llamadas al peer privado. Las suites abren únicamente los fixtures loopback pertinentes. Las reproducciones adicionales sustituyen `_open` por bytes en memoria y usan SQLite real en directorios temporales.
- Única edición deliberada de entrega: este informe. El runner canónico genera sus cachés habituales (bytecode, duraciones y artefactos de pytest); no son cambios de implementación. El estado Git comprobado después del runner no muestra modificaciones rastreadas.

## Bloqueantes nuevos

### R3 — Alta: un mensaje de cliente se certifica como respuesta final del agente

**Ubicación:** `plugins/platforms/a2a/outbound.py:75-81,118-120,328-347,362-365,374-375`.

`_validate('message', ...)` admite `ROLE_USER`, `ROLE_UNSPECIFIED`, 0 y 1. Esto es necesario parcialmente para mensajes de historial, pero `_event` no impone el rol de servidor a la variante Message de StreamResponse. Además, solo exige contexto cuando el propio payload dice ROLE_AGENT. Por tanto, este resultado malformado en su posición de respuesta se guarda como `observed`:

```json
{"message":{"messageId":"m","role":"ROLE_USER","parts":[{"text":"echo"}]}}
```

El consumidor cierra el stream inmediatamente. Si había a continuación un Task válido con sus IDs, lo descarta. `resume` devuelve la observación sin task ID y no puede hacer GetTask. No se produce un duplicado, pero se pierde la correlación recuperable por la misma clase de certificación prematura que motivó R2.

**Fuente de contrato:** `correction-a2a-v1.0.0.proto:244-259` define ROLE_USER como cliente→servidor, ROLE_AGENT como servidor→cliente y exige contexto para mensajes de servidor; `:775-781` define específicamente StreamResponse.message como mensaje del agente. Aceptar ROLE_USER en Task.history no justifica aceptarlo como respuesta final.

**Salida ejecutada, `Client.send`/`resume` reales con stream de dos eventos en memoria:**

```text
top_level_role 'ROLE_USER' state observed task None events 1 calls ['SendStreamingMessage']
top_level_role 'ROLE_UNSPECIFIED' state observed task None events 1 calls ['SendStreamingMessage']
top_level_role 0 state observed task None events 1 calls ['SendStreamingMessage']
top_level_role 1 state observed task None events 1 calls ['SendStreamingMessage']
```

**Arreglo mínimo:** después de la validación estructural y antes de mutar/persistir, exigir que la variante Message de StreamResponse tenga rol normalizado ROLE_AGENT y contexto no vacío. No imponer esta restricción indiscriminadamente a Task.history: allí ROLE_USER sigue siendo válido. Añadir negativos para los cuatro valores, con y sin contexto, como primer evento y después de un ack; comprobar ausencia de mutación, no certificación y cero reenvíos. Mantener positivo ROLE_AGENT/2 y los historiales de cliente.

### R4 — Media: overflow numérico se convierte en Infinity durable y salida no JSON

**Ubicación:** `plugins/platforms/a2a/outbound.py:116-117,123-129,163-166,342-348,505,540`.

`parse_constant` rechaza los literales NaN/Infinity, pero no un número como `1e999`: el parser estándar lo transforma en `float('inf')`. La validación de Part.data/metadata no comprueba finitud y `json.dumps` permite Infinity por defecto. Un Message ROLE_AGENT válido salvo ese contenido se certifica `observed` y queda persistido con `Infinity`. La salida CLI del registro también usa ese literal, que no pertenece a JSON. Esto contradice la validación de datos JSON/ProtoJSON y hace que consumidores JSON estrictos no puedan leer un resultado que el cliente certificó como válido.

**Reproducción ejecutada:** pasar por `_wire_json` un envelope correlacionado con Message válido, `contextId: "c"` y `parts: [{"data": 1e999}]`; después llamar `_event` y cargar SQLite.

```text
numeric_overflow observed [{"message": {"messageId": "m", "contextId": "c", "role": "ROLE_AGENT", "parts": [{"data": Infinity}]}}]
```

El problema no requiere enviar el literal prohibido Infinity por la red. Tampoco es una afirmación de ejecución remota o exfiltración: es aceptación y persistencia de un valor no representable como JSON válido.

**Arreglo mínimo:** usar un `parse_float` que rechace resultados no finitos (incluidos overflow positivo/negativo), o verificar recursivamente finitud inmediatamente después de decodificar, antes de cualquier cambio de estado. Añadir `allow_nan=False` en serialización durable/salida como segunda defensa, sin reemplazar la validación previa. Probar `1e999` y `-1e999` en Part.data, metadata y valores anidados por SSE/GetTask, preservando el último estado durable. Mantener positivos para valores finitos representables.

## Reproducción mínima sin red

Desde el checkout, con `.venv/bin/python`, el siguiente código reproduce R3 y R4 sin contactar ningún endpoint ni modificar el código:

```python
import io, json, os, tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from plugins.platforms.a2a.outbound import Client, Store, _wire_json

os.environ['SECOND_REVIEW_TOKEN'] = 'fixture-only-credential'
cfg = dict(enabled=True, peer='zuri', runtime='codex', host='zurqui',
           url='https://zurqui/rpc', token_env='SECOND_REVIEW_TOKEN')
with tempfile.TemporaryDirectory() as directory:
    client = Client(cfg, Store(Path(directory) / 'state'))
    local_id = client.prepare('hello')
    calls = []

    @contextmanager
    def response(body, stream):
        calls.append(body['method'])
        results = [
            {'message': {'messageId': 'm', 'role': 'ROLE_USER',
                         'parts': [{'text': 'echo'}]}},
            {'task': {'id': 'real-task', 'contextId': 'real-context',
                      'status': {'state': 'TASK_STATE_WORKING'}}},
        ]
        wire = ''.join('data: ' + json.dumps(dict(
            jsonrpc='2.0', id=body['id'], result=result)) + '\n\n'
            for result in results).encode()
        yield io.BytesIO(wire).read

    with patch.object(client, '_open', response):
        result = client.send(local_id)
        resumed = client.resume(local_id)
    print(result['local_state'], resumed['task_id'], calls)

    another_id = client.prepare('another')
    record = client.store.claim_send(another_id, client.binding)
    raw = json.dumps(dict(jsonrpc='2.0', id=another_id, result={
        'message': {'messageId': 'm', 'contextId': 'c', 'role': 'ROLE_AGENT',
                    'parts': [{'data': 'NUMERIC_MARKER'}]}}))
    raw = raw.replace('"NUMERIC_MARKER"', '1e999')
    client._event(record, _wire_json(raw), another_id)
    print(record['local_state'], json.dumps(client.store.load(another_id)['events']))
```

## Correcciones previas verificadas

- **R1:** `send` y `resume` mantienen `Store.writer` durante toda la operación (`outbound.py:352-376,444-465`). El observador que no adquiere flock carga sin guardar; sin task ID tampoco modifica prepared/uncertain/observed. Se ejecutaron las regresiones multiproceso con barreras pre-ack, post-ack y durante GetTask (`test_a2a_outbound_recovery.py:457-534`), la consulta prepared (`:537-546`) y las pruebas de muerte de procesos. La reclamación SQLite sigue antes de la red y no permite un segundo send. No encontré una nueva carrera bloqueante en esta coordinación bajo el alcance declarado POSIX/disco privado/procesos corregidos.
- **R2, ejemplos exactos:** Message `{}` y Task sin status ahora producen ProtocolError; reproducciones adicionales confirmaron `memory_preserved True` y `durable_preserved True` para ambos. La copia candidata evita IDs parcialmente publicados cuando falla una validación posterior. No obstante, R3/R4 impiden dar por cerrada la validación completa.
- **Durabilidad/errores:** se guardan IDs antes del siguiente evento; errores SQLite/fsync se propagan. Si falla fsync después del commit, puede existir un estado durable posterior: el runbook lo advierte y no promete rollback. Un error de transporte no sustituye el estado remoto por FAILED.
- **SSE/transporte:** las pruebas ejecutadas cubren delimitación CR/LF/CRLF, BOM, fragmentación UTF-8, comentarios, truncamiento, límites y deadline. No hay reconexión ni reenvío automático, redirects, AgentCard fetch ni descarga/ejecución de Part.url.
- **Seguridad local:** no se observaron secretos reales, shell=True, os.system, eval/exec ni pickle en el módulo. SQL usa parámetros; URL y binding se restringen; bearer no se guarda como header y errores CLI no imprimen el cuerpo remoto. Esto no es garantía de detección de todo secreto posible. Permisos/dueño/tipo de una BD preexistente siguen siendo endurecimiento declarado pendiente, no un R1 nuevo.

## Ejecución independiente completa del conjunto acordado

Runner canónico, `.venv` existente, entorno limpio y reintentos de archivo deshabilitados:

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py --file-retries 0
```

Salida real, exit 0:

```text
=== Summary: 11 files, 478 tests passed, 0 failed (100% complete) in 19.2s (24 workers) ===
```

| Archivo | Pasan |
|---|---:|
| tests/plugins/test_a2a_outbound_recovery.py | 58 |
| tests/plugins/test_a2a_outbound_validation.py | 118 |
| tests/plugins/test_a2a_plugin.py | 105 |
| tests/plugins/test_a2a_phase23.py | 45 |
| tests/plugins/test_a2a_schema_registration.py | 1 |
| tests/plugins/test_a2a_tools_gate.py | 6 |
| tests/tools/test_a2a_reason_roundtrip.py | 5 |
| tests/tools/test_approval.py | 134 |
| tests/tools/test_approval_interrupt.py | 2 |
| tests/tools/test_approval_config_readonly.py | 3 |
| tests/gateway/test_approvals_command.py | 1 |
| **Total comprobado por Python** | **478** |

La estimación inicial `~338` del runner no es el total parametrizado. Se verificó la suma real por archivo. Esta es toda la selección solicitada, no toda la suite de Hermes. R3/R4 son reproducciones adicionales, no tests existentes fallidos: las 478 pruebas verdes no cubren esos defectos.

Ruff sobre los cuatro archivos Python, con `.venv/bin/python -m ruff check --no-cache ...`: **All checks passed!**, exit 0. `git diff --check`: sin diagnósticos. Para los cuatro archivos Python y el runbook nuevos se ejecutó además `git diff --no-index --check /dev/null ARCHIVO`: salida vacía, exit 1 por tratarse de archivos nuevos, no por errores de whitespace.

## Alcance diferido y puertas humanas

**No son defectos ocultos de esta fase:** la entrega es CLI manual opt-in, no tool nativo ni integración conversacional completa. Runbook `:15-25,180-218` y correction-report `:143-157` lo declaran correctamente. No presentan los mocks ni las pruebas locales de aprobación como recepción/approve/deny real de Carlos.

El fixture `tests/plugins/fixtures/a2a_outbound_peer.py:71-75` convierte working en completed al consultar GetTask; no demuestra supervivencia de una ejecución real de Codex. El puente Carlos↔aprobación de Codex no está implementado; codex-a2a real de Zuri no está aceptado ni probado. No se verificó endpoint privado, identidad real, TLS real, aprobación/denegación humana ni efectos posteriores correlacionados.

Mantener pendientes revisión posterior a las correcciones, publicación/MR por el flujo autorizado, aceptación real coordinada y autorización separada de arranque. Este informe no autoriza llamadas a zurqui, despliegue, inbound, puertos públicos, cron, callbacks ni jobs automáticos. No se implementó ningún arreglo durante esta revisión.
