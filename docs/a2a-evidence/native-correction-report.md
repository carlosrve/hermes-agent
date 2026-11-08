# Corrección N1/N2 — A2A nativo diferido, send sigue bloqueado

**Corrección implementada y probada; pendiente nueva revisión independiente.** No es una aprobación de la propia entrega, integración E2E ni autorización de arranque. `native-independent-review.md` permanece intacto, con su veredicto histórico `passed: false`.

## Identidad y alcance

- Solo checkout `/workspace/a2a-integration`, rama `feature/a2a-outbound-recovery`, HEAD/base `1c8aaad2180bbf2fc34f097ab90d069170584ccd`.
- Skills cargados: hermes-agent, test-driven-development, hermes-source-fork-integration. Leídos primero review, plan, implementación nativa e informe previo; luego assembly, resolución por toolsets, unwrap, ambos executors y dispatcher.
- Sin commits, staging, push, PR, configuración operativa, despliegue, inicio de servicios, inbound público, cron, autojobs o llamadas al peer real. `/opt/hermes` no se modificó. Suite previa usa fixtures loopback; nuevos casos nativos prohíben transporte.
- SHA256 `outbound.py` antes/después: **`6efca80535214c90769af2828ef411f0fef6fe0b58ae7545bafc1997601376f0`**, idéntico al review. Tampoco se editó `native_tools.py`. Hashes en `native-correction-hashes.log`.

## Inventario confiable real y arreglo

`valid_tool_names` sigue siendo el conjunto visible al modelo, posterior al assembly. No se amplía ni se usa como inventario global de permisos.

La fuente existente para autorización diferida es **`agent.tool_executor._tool_search_scoped_names(agent)`**. Resuelve `model_tools.get_tool_definitions(enabled_toolsets=agent.enabled_toolsets, disabled_toolsets=agent.disabled_toolsets, skip_tool_search_assembly=True)` y `scoped_deferrable_names`: exactamente el universo autorizado por la selección de esta sesión que ya verifica el unwrap. Su caché por agente incluye scope/generación de registry y selección enabled/disabled. No es el catálogo global de discovery ni `_last_resolved_tool_names`.

Se reutiliza ese inventario, en vez de crear un segundo snapshot divergente:

1. Nuevo `_execution_tool_names(agent, function_name)` localizado al tool nativo. Si el nombre nativo está visible, conserva la ruta no diferida. Si está diferido, exige bridge `tool_call` visible y selección **explícita** de `a2a_outbound`; devuelve el inventario scoped existente, sin unir listas arbitrarias. Solo tool_search/tool_describe, discovery o pertenencia global al registry no conceden permiso.
2. Los executors secuencial y concurrente consultan el helper **dentro** de su closure de ejecución, no al crearla. Se comprueban revocaciones entre unwrap y dispatch. No se aceptan sesión, tools, scope o autorización procedentes de JSON.
3. El gate nativo en `model_tools.handle_function_call` conserva sesión/opt-in/grant y añade la selección real `_select_tool_names` en dispatch. Esto preserva también la resta final por **bundles/aliases deshabilitados**, no solamente el nombre literal `a2a_outbound`. Se encontró y reprodujo un defecto adicional no diferido: un bundle disabled que contenía el tool no bloqueaba su grant visible.
4. El handler sigue revalidando configuración sin confiar en la caché de disponibilidad. Revocar enabled del plugin después del unwrap bloquea. Desregistrar, quitar selección o quitar el bridge también bloquea. Los hooks de denegación existentes preceden al handler; no se sustituyeron por el grant.
5. Otros tools conservan exactamente la lista visible previa y el comportamiento sandbox/async. No se modifica `_run_async`, el assembly, el catálogo, el pipeline de aprobación ni el sandbox.

**Límite:** esta es metadata de Python confiable para el runtime, no una capability frente al mismo UID. Las llamadas directas a `handle_function_call` siguen requiriendo un inventario autorizado explícito del caller; no adquieren permisos por un JSON `tool_call` o por discovery. No se afirma un nuevo mecanismo general de permisos ni recarga instantánea universal de configuración.

## TDD y cobertura ejecutada

- `native-correction-red-exact.log`: reproducción del reviewer con assembly real auto/on/off, unwrap real y executor real. **2 fallos auto/on**, con `{'status': 'blocked', 'reason': 'trusted_grant_required'}`; control off pasa. `native-correction-red.log` conserva el primer fallo equivalente con assertion de local_state.
- `native-correction-green.log`: 41 tests pasan tras corregir el executor secuencial.
- `native-correction-red-concurrent.log`: ampliar el mismo recorrido al executor concurrente expuso **2 fallos** restantes auto/on. `native-correction-green-concurrent.log`: 44 pasan tras reutilizar el helper en invoke_tool.
- `native-correction-red-revocation.log`: **1 fallo y 11 controles pasan**; bundle disabled en modo no diferido permitía prepare. `native-correction-green-revocation.log`: 56 pasan tras revalidar selección en dispatch.
- `native-correction-regressions.log`: 67 tests nativos dispatch pasan. Total **29 casos añadidos** respecto a los 38 anteriores.

Casos nuevos: prepare/show/resume y send bloqueado en auto/on/off por ambos executors; ownership padre/hijo; revocación de selección, disabled literal/bundle, schemas visibles, configuración y registro después del unwrap; sesiones restringidas con grant ausente/vacío/legacy y discovery previo de otra sesión; denegación del hook antes del handler; invoke_tool desde worker async y revocación posterior. La denegación del hook es una fixture de política, **no aprobación humana real**. Los tests de roundtrip comprueban que send no modifica SQLite ni finge notificación; transporte nuevo prohibido. Resume del draft sin task ID es observación local, no un trabajo remoto ni un ack inventado.

Las fixtures anteriores solo sustituían `model_tools.registry`, dejando el resolver de toolsets con otro registro. Se corrigen ambos imports del registry al mismo objeto aislado. La primera suite completa (`native-correction-canonical-suite.log`: 689 pasan, 1 falla) identificó esta inconsistencia en `test_a2a_native_tools.py`; no se relajó ninguna assertion funcional para corregirla.

## N2 — configuración documentada

Runbook y estado actual del plan ahora escriben el fallback completo:

- Preferido: `plugins.entries.platforms/a2a.settings.outbound`.
- Fallback legacy: **`plugins.entries.platforms/a2a.config.outbound`**.
- No existe fallback a `config.outbound` global ni `outbound` top-level.

Comprobado en `hermes_cli/plugins.py:253–263`. Se conserva la investigación histórica del plan identificada como tal.

## Verificación final reproducible

Desde el checkout, `.venv` existente, sin reintentos por archivo:

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/test_model_tools.py tests/test_model_tools_async_bridge.py --file-retries 0
```

**Exit 0: 15 archivos, 690 tests pasados, 0 fallidos, 19.2 s**, `native-correction-verified-suite.log`. Incluye toda la selección canónica solicitada y nuevos casos. No es toda la suite Hermes.

```bash
scripts/run_tests.sh tests/tools/test_tool_search.py tests/tools/test_tool_search_multiquery.py tests/tools/test_connector_local_batches.py --file-retries 0
```

**Exit 0: 3 archivos adicionales, 77 tests pasados, 0 fallidos, 3.1 s**, `native-correction-tool-search-verified.log`. Conteos extraídos y sumados con Python en `native-correction-counts.json`.

La primera ejecución adicional dio 73 pasados/4 fallidos: faltaba `jsonschema` en la venv; `validate_deferred_call_args` tiene fallback required-only cuando falta ese paquete. Se verificó `find_spec('jsonschema') == None` y se instaló **exclusivamente en `/workspace/a2a-integration/.venv`** con `.venv/bin/python -m pip install --no-cache-dir jsonschema` (exit 0). Versión instalada 4.26.0 y dependencias detalladas en `native-correction-venv-jsonschema.log`. Sin cambiar pyproject, sistema ni runtime. Se repitieron las dos suites completas con esa dependencia presente: ambos resultados finales anteriores son posteriores a la instalación. No se alteró el validador para ocultar los fallos.

```bash
.venv/bin/python -m ruff check --no-cache agent/tool_executor.py agent/agent_runtime_helpers.py model_tools.py plugins/platforms/a2a/native_tools.py plugins/platforms/a2a/tools.py plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
git diff --check
```

Ruff **exit 0, All checks passed!** (`native-correction-final-lint.log`); diff check **exit 0, sin diagnósticos** (`native-correction-diff-check.log`). Se inspeccionó el delta de código; diff check cubre rastreados, Ruff incluye explícitamente módulos/tests nuevos.

## Archivos de esta corrección y procedimiento reutilizable

Cambios de código: `agent/tool_executor.py`, `agent/agent_runtime_helpers.py`, una condición adicional en `model_tools.py`. Tests: `tests/plugins/test_a2a_native_dispatch.py`, aislamiento de fixture en `tests/plugins/test_a2a_native_tools.py`. Docs: runbook, estado actual del plan y este informe/logs `native-correction-*`. No se atribuyen a esta corrección los otros cambios preexistentes del checkout. No se instaló ningún skill fuera del proyecto.

Lección para revisar tools diferidos: reproducir selección real → assembly auto/on/off → unwrap con esquema real → cada executor, y revocar **después** del unwrap; distinguir inventario autorizado scoped de schemas visibles y globals. Un control directo con `enabled_tools=['tool']` no prueba el camino de Tool Search. Revalidar disabled mediante el resolver completo, incluidos bundles; probar el mismo flujo sin diferir. Conservar RED, fallos de entorno y conteos finales separados de aceptación externa.

## Punto de parada

**Detenido para revisión independiente. Send continúa incondicionalmente bloqueado**, sin red, claim, notificación, decisión ni aprobación falsa. No se implementó aprobación ni consumo de permisos. Siguen bloqueantes el transportista aislado del mismo UID, superficie humana autenticada/recepción/approve/deny de Carlos, bridge durable con binding/TTL/replay, contrato real Codex/zuri, URL privada/TLS/SAN/bearer y pruebas reales de continuidad/cortes/efecto único. Fixtures y tests verdes no satisfacen esas puertas ni autorizan publicación o launch.
