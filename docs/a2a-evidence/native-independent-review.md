# Revisión independiente — fundamento nativo A2A con send bloqueado

**`passed: false`**, exclusivamente para el fundamento nativo prepare/show/resume + send bloqueado. Hay un defecto reproducible de usabilidad en el despacho diferido, no un bypass de envío. **No acredita integración completa, aprobación humana, peer real, despliegue ni autorización de inicio.**

## Identidad y alcance

- Checkout `/workspace/a2a-integration`, rama `feature/a2a-outbound-recovery`, HEAD/base comprobado `1c8aaad2180bbf2fc34f097ab90d069170584ccd`.
- origin `https://github.com/carlosrve/hermes-agent.git`; upstream `https://github.com/NousResearch/hermes-agent.git`.
- SHA256 ejecutado de `plugins/platforms/a2a/outbound.py`: **`6efca80535214c90769af2828ef411f0fef6fe0b58ae7545bafc1997601376f0`**, idéntico a `third-independent-review.md`. El transporte previamente revisado permanece sin cambios.
- SHA256 de `native_tools.py`: `6625dc11fe39a715a7d4a4d7c8f841b18bbe245efcd76c4a4559126384443b84`.
- Leídos el informe nativo, tercer review, módulo nativo completo, tests nativos completos, diff rastreado contra base, runbook, registro/plugin config y recorridos reales de assembly/executor/dispatch; inspeccionadas las rutas Client/Store reutilizadas.
- Skills cargados: requesting-code-review, hermes-agent y hermes-source-fork-integration con referencia A2A. La instrucción específica de revisión excluye auto-fix, staging, commits y publicación.
- Único archivo de entrega escrito: este informe. Sin instalaciones, cambios de implementación/configuración operativa, commits, push, launch o llamadas a peers reales. Runner con `.venv` existente, BD temporales, fixtures loopback autorizados y cachés habituales de pruebas. Las sondas adicionales usan contexto temporal y transporte prohibido.

## N1 — Bloqueante de corrección: el grant confunde schemas visibles con herramientas autorizadas

**Ubicación:** `model_tools.py:881–887,812–815`; integración con `agent/agent_init.py:1062–1067`, `agent/tool_executor.py:371–404,1536–1550` y `tools/tool_search.py:339–374`.

`agent.valid_tool_names` se construye de los schemas **después** de la sustitución por tool_search/tool_describe/tool_call. Un plugin como a2a_outbound se difiere con Tool Search auto/on. Aunque su toolset fue seleccionado explícitamente, el nombre nativo ya no figura en valid_tool_names. El executor pasa esa lista como enabled_tools; el nuevo gate rechaza prepare/show/resume con `trusted_grant_required`. El unwrap previo valida correctamente el catálogo de la sesión, pero no amplía esa lista visible.

**Efecto real:** el recorrido normal con Tool Search activo anuncia la herramienta mediante el catálogo, pero no permite utilizarla. Funciona con schemas no diferidos. No es ampliación de alcance exigir que el bridge ya declarado funcione; el informe nativo afirma cubrirlo. Sus tests lo omiten porque inyectan manualmente `enabled_tools=['a2a_outbound']` o un agente con ese nombre visible.

### Reproducción independiente ejecutada

Desde el checkout, `.venv/bin/python -B -c`, entorno limpio, registro aislado en memoria. El siguiente cuerpo es reproducible sin escribir tests, configurar el runtime ni conectar a un peer:

```python
import os, tempfile, json
from pathlib import Path
from types import SimpleNamespace

with tempfile.TemporaryDirectory() as d:
    os.environ['HERMES_HOME'] = d
    import model_tools
    from hermes_constants import set_hermes_home_override
    set_hermes_home_override(Path(d))
    os.environ['NATIVE_TEST_BEARER'] = 'fixture-native-credential'
    from plugins.platforms.a2a import tools
    import tools.registry as registry_module
    from tools.registry import ToolRegistry
    registry = ToolRegistry()
    registry_module.registry = registry
    model_tools.registry = registry
    config = dict(enabled=True, peer='zuri', runtime='codex', host='zurqui',
                  url='https://zurqui/rpc', token_env='NATIVE_TEST_BEARER')
    tools.register_tools(SimpleNamespace(
        get_config=lambda *a: config,
        register_tool=lambda **kw: registry.register(**kw)))
    from plugins.platforms.a2a.outbound import Client
    def forbidden(*a, **k):
        raise AssertionError('NETWORK FORBIDDEN')
    Client._open = forbidden
    from tools.tool_search import assemble_tool_defs, ToolSearchConfig
    from agent.tool_executor import _resolve_sequential_dispatch, _ToolCallRef
    direct = registry.get_definitions({'a2a_outbound'})
    assembly = assemble_tool_defs(direct, config=ToolSearchConfig(
        enabled='auto', threshold_pct=5, search_default_limit=5, max_search_limit=20))
    names = {t['function']['name'] for t in assembly.tool_defs}
    print('actual advertised names:', sorted(names))
    assert 'tool_call' in names and 'a2a_outbound' not in names
    agent = SimpleNamespace(session_id='owner', valid_tool_names=names,
        enabled_toolsets=['a2a_outbound'], disabled_toolsets=[],
        _context_engine_tool_names=set(), _memory_manager=None, quiet_mode=False)
    args = {'action': 'prepare', 'message': 'hello'}
    # Entrada real del executor después del unwrap del bridge.
    ref = _ToolCallRef('a2a_outbound', args, 'terminal', 'call', [])
    result = json.loads(_resolve_sequential_dispatch(agent, ref, []).execute(args))
    print('real executor after unwrap:', result)
    assert result == {'status': 'blocked', 'reason': 'trusted_grant_required'}
    agent.valid_tool_names = {t['function']['name'] for t in direct}
    result = json.loads(_resolve_sequential_dispatch(agent, ref, []).execute(args))
    print('nondeferred control:', result['local_state'])
    assert result['local_state'] == 'prepared'
```

Salida real, exit 0:

```text
handler available: True
actual advertised names: ['tool_call', 'tool_describe', 'tool_search']
real executor after unwrap: {'status': 'blocked', 'reason': 'trusted_grant_required'}
nondeferred control: prepared
```

La sonda ejecutada imprimió además el check_fn y la suma 661. No ejecuta un modelo ni pretende validar toda una sesión E2E. Tres intentos iniciales con registry global/discovery no aislaron correctamente el registro: devolvieron catálogo vacío y fallaron assertions antes de alcanzar el caso. No se usan como evidencia de un segundo bug. La reproducción anterior aísla el registro explícitamente, usa el assembly y executor reales y demuestra el defecto con control positivo.

**Arreglo mínimo propuesto:** separar el grant confiable de ejecución del conjunto de schemas visibles; conservar un snapshot de herramientas autorizadas anterior al assembly y pasarlo desde el agente al dispatcher. No usar el catálogo global como fallback, no aceptar grants JSON y no eliminar el requisito de opt-in explícito ni la prevalencia de disabled. Alternativamente, mantener esta herramienta explícitamente no diferida en esta fase, con documentación y test que lo prueben. Añadir regresión con assembly auto/on real + executor después de unwrap, control no diferido, hijo restringido y grant vacío. Repetir la revisión tras corregir.

## N2 — Observación documental menor, no bloqueante adicional

`docs/a2a-outbound-runbook.md:25–27` llama al fallback `config.outbound` sin su prefijo. `hermes_cli/plugins.py:253–263` realmente busca **`plugins.entries.platforms/a2a.config.outbound`**, no un `config.outbound` global ni `outbound` top-level. La ruta preferida `plugins.entries.platforms/a2a.settings.outbound` sí es correcta y el test de discovery pasa. Arreglo mínimo: escribir la ruta completa del fallback para evitar una configuración silenciosamente unavailable.

## Garantías comprobadas dentro del alcance

| Área | Resultado |
|---|---|
| Opt-in doble | `native_tools.py:23–36,60–66` revalida config en handler, además del check_fn; config ausente/malformed/disabled bloquea. Dispatch exige sesión y grants explícitos; disabled prevalece. Sin fallback global nativo. N1 afecta disponibilidad, no permite eludir el gate. |
| Ownership | Home proviene del contexto Hermes; sesión de kwargs Python del agente, no task_id terminal ni JSON. Namespace SHA256 por sesión desde el insert (`39–44`). Tests rechazan sesión hija y profile distinto antes de red. Hash/DispatchScope/0700 no son capabilities no falsificables frente al mismo UID. |
| Argumentos | Allowlist exacta por action, local_id 32 hex, mensaje UTF-8 no vacío <=64 KiB; rechaza approved/force/scope/session/profile/endpoint/secretos/RPC elegidos por el modelo (`67–82`). |
| prepare/show | prepare persiste localmente y rechaza bearer activo en texto; exige esa variable aunque no haga red. show devuelve únicamente snapshot fijo validado, sin draft ni artefactos; no constituye tarjeta de aprobación ni lector de resultados. Falta bearer no impide show. |
| send | No hay rama que llame Client.send, claim_send, notificación, decisión o consumo. Con draft válido devuelve blocked/bridge_missing y notification_delivered=false (`94–97`); repetición y YOLO no alteran BD. IDs/config inválidos también bloquean, con razón genérica distinta: no prometer siempre la misma reason. |
| resume | Únicamente Client.resume/GetTask (`91–92`; outbound `400–440`). Sin task ID o con otro escritor activo observa localmente. input-required conserva intervención y no acredita aprobación. Como send nativo no funciona y no importa registros CLI, el camino remoto solo se ejercita con ack sembrado en fixture; no es aún un flujo de trabajos reales usable de principio a fin. |
| Salida y logs | Snapshot de campos acotados, estados/local_id validados y excepciones de Store/transporte reducidas a request_unavailable. Sin logger/print de contenido remoto en wrapper, ni events/metadata/URL/IDs remotos en su salida. Se conservan límites del transporte/registro revisado; no equivale a redacción universal de todos los secretos ni elimina los transcript/hooks normales de argumentos del framework. |
| Legacy | Registro nativo independiente; cinco herramientas legacy conservan gate/handlers. Import POSIX lazy; test de dependencia unavailable no rompe registro legacy. No incorporación a core ni activación inbound. |
| model_tools genérico | Delta localizado por nombre; no cambia `_run_async`, handlers async o kwargs de otros tools. Pasan tests genéricos sync y async bridge. Recursión manual de tool_call conserva restricciones, pero no resuelve la discrepancia del grant real N1. |

## Suite canónica independiente

Comando exacto ejecutado desde `/workspace/a2a-integration`, `.venv` existente, sin instalaciones ni reintentos por archivo:

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/test_model_tools.py tests/test_model_tools_async_bridge.py --file-retries 0
```

Salida real, exit 0:

```text
=== Summary: 15 files, 661 tests passed, 0 failed (100% complete) in 19.8s (24 workers) ===
```

Conteos por archivo, en el orden del comando: **58, 219, 105, 45, 2, 6, 5, 134, 2, 3, 1, 3, 38, 28, 12**. Suma comprobada ejecutando Python: **661**. El estimado inicial ~398 del runner no es el total parametrizado. No es toda la suite Hermes. La sonda N1 no se suma a pytest; demuestra una laguna pese a la suite verde.

```bash
.venv/bin/python -m ruff check --no-cache model_tools.py plugins/platforms/a2a/native_tools.py plugins/platforms/a2a/tools.py plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
git diff --check
```

Ruff: `All checks passed!`, exit 0. Diff check: sin diagnósticos, exit 0; solo cubre rastreados. No se hizo stash/baseline destructivo ni se modificó implementación para corregir hallazgos.

## Puertas pendientes

N1 requiere corrección y nueva revisión antes de acreditar este fundamento nativo. Independientemente, siguen pendientes aislamiento OS/servicio del transportista, superficie humana autenticada inaccesible al agente, recepción/approve/deny personales de Carlos, binding/TTL/replay y consumo durable atómico, contrato real Codex/zuri, URL privada/SAN/TLS/bearer y pruebas reales de continuidad/cortes/efecto único. No dar el bearer al proceso del agente alegando que un scope Python lo protege. Nada aquí autoriza MR/commit/push por esta revisión ni despliegue/arranque, inbound público, cron o jobs automáticos.
