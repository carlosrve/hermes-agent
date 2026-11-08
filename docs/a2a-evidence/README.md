# Evidencia de la implementación aislada

## Resultado final

`28-final-suite.txt`: **352 passed, 0 failed**, 10 archivos, 14.0 s.
Incluye **50 casos nuevos outbound**, 162 regresiones A2A existentes y
140 regresiones de aprobaciones existentes. Se usó el runner canónico con
`--file-retries 0`: no hubo reintentos que ocultaran fallos. El estimador del
runner muestra `~328` por AST; el conteo real ejecutado parametrizado es 352.
No se ejecutó la suite completa de todo Hermes.

`29-final-lint.txt`: Ruff `All checks passed!`.
`30-whitespace.txt`: chequeo git de los archivos nuevos, sin diagnósticos.
Para `git diff --no-index --check /dev/null FILE`, código 1 sin diagnóstico
solo señala que el archivo es nuevo; no es un fallo de whitespace.
Se retiró una línea vacía extra al EOF después del último test; sin cambio
semántico. `artifact-manifest.json` identifica los artefactos finales por SHA256.

Base/rama/remotes y runtime final: `checkout-verification.txt`.
Dependencias de pruebas exactas: `test-environment.txt`.
Interfaz CLI realmente ejecutada: `cli-help.txt`.

## Comandos reproducibles

Directorio: `/workspace/lfc/a2a-integration`.
El código nuevo de ejecución solo usa stdlib; la venv es para tests/lint.

```bash
python -m venv .venv
.venv/bin/pip install -r docs/a2a-evidence/test-environment.txt

scripts/run_tests.sh \
  tests/plugins/test_a2a_outbound_recovery.py \
  tests/plugins/test_a2a_plugin.py \
  tests/plugins/test_a2a_phase23.py \
  tests/plugins/test_a2a_schema_registration.py \
  tests/plugins/test_a2a_tools_gate.py \
  tests/tools/test_a2a_reason_roundtrip.py \
  tests/tools/test_approval.py \
  tests/tools/test_approval_interrupt.py \
  tests/tools/test_approval_config_readonly.py \
  tests/gateway/test_approvals_command.py \
  --file-retries 0

.venv/bin/ruff check \
  plugins/platforms/a2a/outbound.py \
  tests/plugins/test_a2a_outbound_recovery.py \
  tests/plugins/fixtures/a2a_outbound_peer.py

.venv/bin/python -m plugins.platforms.a2a.outbound --help
```

Todos los ciclos focalizados usaron exactamente:

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py --file-retries 0
```

La redirección del stdout/stderr del runner produjo los archivos numerados;
son salidas reales, no resultados sintetizados.

## TDD por tramos verticales

| Evidencia | Comportamiento |
|---|---|
| 01 red → 02 green | solicitud/correlación durable antes de red |
| 03 red → 04 green | SendStreamingMessage HTTP real, IDs, estado y artefacto |
| 05/05b red → 06 green | CLI en subprocess, recuperación tras reinicio de ambos lados |
| 07 red → 08 green | opt-in/config, secreto env, intervención y no guardar bearer reflejado |
| 09 red → 10 green | claim transaccional para impedir dos envíos concurrentes |
| 11 red → 12 green | límite temporal pese a heartbeats y CAS de recuperación |
| 15 red → 16 green | parar por intervención, Message durable, formas remotas inválidas |
| 17 red → 19 green | deadline también durante cabeceras HTTP lentas |
| 24 red → 25 green | JSON profundo/duplicado/NaN |
| 27 red → 28 green | GetTask con error JSON-RPC malformado |

Se añadieron además verificaciones de los comportamientos ya implementados:
framing SSE, fallos fsync/SQLite, rechazo de redirecciones/binding cambiado,
kill del cliente tras ack durable y caída del servidor durante working.

## Fallos de entorno encontrados y resueltos honestamente

- `05-red.txt`: el guard de procesos del runner no pudo comprobar parentesco
  por ausencia de `psutil`. Se instaló `psutil` en **la venv aislada** y se
  repitió RED (`05b`); no se desactivó el guard ni se tocaron procesos de Hermes.
- `13-regression.txt`: faltaba `snowballstemmer` en colección de una suite.
  No se trató el parcial de 161 tests como éxito. Se instaló en la venv y se
  repitió (`14`: 162 passed).
- `18-approval-regression.txt`: dos tests requerían `prompt_toolkit`.
  Se instaló en la venv y se repitió (`20`: 140 passed).
- Todos estos fallos se conservan para no presentar una historia falsa de
  ejecución sin problemas. Los archivos `23`/`25` son pasadas intermedias;
  la aceptación de código final corresponde a `28`.

## Qué prueban los procesos HTTP reales

`tests/plugins/fixtures/a2a_outbound_peer.py` es un servidor loopback creado
solo durante el test. El cliente corre también como subprocess independiente:

- `durable`: task guardado en archivo por el fixture; nuevo proceso servidor
  puede responder GetTask y devolver artefacto. Esto **no es codex-a2a**.
- `lost`: el fixture deliberadamente no guarda task; tras reiniciar devuelve
  -32001. El cliente conserva working y marca remote_missing, sin recrearlo.
- `before-ack`: el fixture registra el encargo y corta antes del ID remoto;
  resume no emite ninguna petición, aunque el fixture sí tenga task en disco.
- `hold`: entrega ID/context y mantiene ejecución. Se comprueba la BD local
  mientras el stream continúa; se mata el cliente o el servidor en casos
  separados y luego se verifica GetTask, nunca otro SendStreamingMessage.
- `drip` / `headers`: tráfico lento no extiende indefinidamente el deadline.
- `redirect`: se rechaza HTTP 307; no se sigue la URL anunciada.

Los registros de llamadas del fixture se inspeccionan en los tests y están en
sus directorios temporales; no se recopilaron ni inventaron capturas de un
peer privado. Los fixtures son cerrados por los context managers de pruebas.

## Pendiente / no demostrado

- Revisión independiente, commit, push/MR y despliegue: **no realizados**.
- URL privada real, TLS, bearer y AgentCard de zuri: **sin coordinar**.
- Compatibilidad real de codex-a2a, supervivencia real de su task store y sus
  artefactos: **no probadas**.
- Recepción Carlos → aprobar → ejecución y Carlos → denegar → no ejecución:
  **bloqueadas y obligatorias**. Ni estas fixtures ni las 140 regresiones
  existentes sustituyen esa prueba humana. Este delta no instala un puente
  entre input-required remoto y la cola local de aprobaciones.
- El código mantiene una cota de stream, no garantiza timeout de DNS del SO;
  allowlist de hostname corto `zurqui`, POSIX/disco local, sin URIs descargadas.

Ver `../a2a-outbound-runbook.md`: auditoría de código de las aprobaciones,
contrato de seguridad y checklist manual de aceptación. Nada activó inbound,
cron, jobs automáticos, servidores productivos, callbacks ni bypass de permisos.
