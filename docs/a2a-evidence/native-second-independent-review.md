# Segunda revisión independiente — fundamento nativo A2A

**`passed: true`**, limitado a **prepare/show/resume opt-in y send nativo bloqueado**. N1 está corregido en el recorrido diferido real; N2 identifica ahora el fallback correcto. **Sin bloqueantes reproducibles de corrección o seguridad en este alcance.** No acredita aprobación humana, aislamiento OS, integración E2E, peer real, publicación ni autorización de arranque.

## Identidad y disciplina

- Checkout `/workspace/a2a-integration`, rama `feature/a2a-outbound-recovery`, HEAD/base `1c8aaad2180bbf2fc34f097ab90d069170584ccd`, comprobados por Git.
- origin `https://github.com/carlosrve/hermes-agent.git`; upstream `https://github.com/NousResearch/hermes-agent.git`.
- Skills cargados: requesting-code-review, hermes-agent, hermes-source-fork-integration y referencia A2A. La instrucción de revisión específica excluye autofix/stash/staging/commit/publicación del workflow genérico.
- Leídos los dos informes anteriores, los diffs completos de los tres módulos compartidos, registro/plugin/tests rastreados, wrapper y tests nativos completos, runbook y plan. Inspeccionados resolver, assembly, unwrap, dispatcher, closures y política previa al handler.
- Único documento creado por esta revisión: este archivo. Sin instalaciones, cambios de implementación/configuración operativa, commits, push, PR, arranque, cron, inbound público ni llamadas reales a zuri. `/opt/hermes` no se modificó. Runner con `.venv` existente, sus cachés habituales y fixtures temporales/loopback; sonda propia con transporte y claim prohibidos. No se ejecutó un modelo ni una sesión humana E2E.

## Veredicto por contrato

| Contrato | Comprobación independiente |
|---|---|
| N1: grant diferido real | `agent/tool_executor.py:331–380` resuelve el inventario scoped de la selección de la sesión, no los schemas visibles ni `_last_resolved_tool_names`. En auto/on los schemas reales son solo tool_call/tool_describe/tool_search; prepare funciona tras unwrap real. Off conserva el control no diferido. |
| Opt-in explícito | `364–380` exige tool_call visible y selección literal a2a_outbound para el caso diferido. `model_tools.py:881–888` exige sesión, inventario y opt-in aun si el nombre está visible. Discovery previo de otra sesión no concede autoridad. |
| Disabled y revocación | El dispatcher aplica `_select_tool_names` (`model_tools.py:313–334,886`): disabled se resta al final, incluidos bundles. Las closures resuelven al ejecutar (`tool_executor.py:1551–1569`; `agent_runtime_helpers.py:2282–2297`), no al crearlas. La sonda revocó selección, disabled literal/bundle, visibilidad, config y registro después del unwrap en auto/on/off, con ambos executors. Todos bloquearon; configuración se revalida en el handler aunque exista caché. |
| Hooks/restricciones | `_dispatch_authorized_once`, `tool_executor.py:658–708`, mantiene scope → pre-hook → guardrails → ejecución; lo usan las rutas secuencial y concurrente. `invoke_tool:2251–2263` conserva también su denegación directa. No se cambió el pipeline ni sus flags de single-fire. Test nativo de hook denegado pasa; ownership padre/hijo/profile y worker async pasan. Esto es política fixture, no consentimiento humano. |
| N2 | `hermes_cli/plugins.py:253–263` prefiere `plugins.entries.platforms/a2a.settings.outbound` y cae a `plugins.entries.platforms/a2a.config.outbound`. Runbook `25–28` y plan `19–23` coinciden; no es un fallback global. |
| send | `native_tools.py:83–101` carga/valida y devuelve blocked; no llama send, claim, notificación ni consumo. Sonda propia reemplaza `Client._open`, `Client.send` y `Store.claim_send` por fallos; send permanece bloqueado y bytes SQLite idénticos. Los tests también cubren repetición y YOLO. |
| Ownership y salida | Scope/home/sesión provienen de Python confiable, no de JSON/task_id terminal. Namespace desde el insert; argumentos estrictos y snapshot acotado. Tests rechazan autoridad en JSON, owner ajeno y config inválida. No es aislamiento contra terminal/Python del mismo UID. |
| resume | Solo GetTask/observación local. El roundtrip independiente usa draft sin task ID, por tanto no hace red; el test con ack sembrado verifica exclusivamente GetTask y conserva intervención. No acredita un trabajo remoto real. |
| Legacy/defaults | Registro nativo independiente, cliente POSIX lazy; cinco gates legacy intactos. Discovery no activa inbound ni incorpora a2a_outbound a core. |

### Impacto general sobre herramientas NO A2A

El cambio compartido es pequeño pero se revisó por separado: para todo `function_name != 'a2a_outbound'`, `_execution_tool_names` retorna **exactamente** la expresión previa `list(agent.valid_tool_names) if agent.valid_tool_names else None`. Por cortocircuito no consulta el resolver scoped, no añade grants ni carga el cliente nativo. La sonda verificó 16 combinaciones de None/vacío/visibles/bridge con terminal, execute_code, web_search y un nombre connector, prohibiendo consultar el resolver. No se cambian kwargs restantes, async bridge, aliases, sandbox allowlist, guardrails, hooks o aprobaciones de otros tools. Se conserva el fallback global preexistente de execute_code cuando el caller suministra None: esta revisión no lo presenta como nueva garantía ni como regresión introducida.

Pasaron además tests de contexto entre workers, checkpoint, inline memory e interrupción concurrente. No se identificó una regresión general concreta en el delta; **no equivale a ejecutar toda la suite Hermes** ni a certificar todas sus políticas preexistentes.

### Observación documental no bloqueante

Runbook `53–55` sigue abreviando send como si todos los argumentos/configuraciones devolvieran `human_dispatch_bridge_missing`. Con ID/config/scope inválidos devuelve otras razones genéricas, siempre bloqueado. Precisión mínima opcional: «con draft propio válido devuelve human_dispatch_bridge_missing; entradas/config inválidas también bloquean». No afecta N1/N2 ni habilita envío.

## Comandos y resultados reales

Todos desde `/workspace/a2a-integration`; exit 0 salvo que se indique lo contrario. Sin reintentos por archivo ni instalaciones.

```bash
git status --short --branch
git rev-parse HEAD
git remote -v
git diff 1c8aaad2180bbf2fc34f097ab90d069170584ccd -- agent/tool_executor.py agent/agent_runtime_helpers.py model_tools.py
git diff 1c8aaad2180bbf2fc34f097ab90d069170584ccd -- plugins/platforms/a2a/plugin.yaml plugins/platforms/a2a/tools.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py
sha256sum plugins/platforms/a2a/native_tools.py plugins/platforms/a2a/outbound.py
```

Hashes idénticos a la evidencia anterior:

```text
6625dc11fe39a715a7d4a4d7c8f841b18bbe245efcd76c4a4559126384443b84  plugins/platforms/a2a/native_tools.py
6efca80535214c90769af2828ef411f0fef6fe0b58ae7545bafc1997601376f0  plugins/platforms/a2a/outbound.py
```

### Suite canónica requerida

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/test_model_tools.py tests/test_model_tools_async_bridge.py --file-retries 0
```

```text
=== Summary: 15 files, 690 tests passed, 0 failed (100% complete) in 20.5s (24 workers) ===
```

Conteos en orden: 58, 219, 105, 45, 2, 6, 5, 134, 2, 3, 1, 3, 67, 28, 12. Suma comprobada con Python: 690. El estimado inicial ~403 no es el total parametrizado.

```bash
scripts/run_tests.sh tests/tools/test_tool_search.py tests/tools/test_tool_search_multiquery.py tests/tools/test_connector_local_batches.py --file-retries 0
```

```text
=== Summary: 3 files, 77 tests passed, 0 failed (100% complete) in 3.4s (24 workers) ===
```

Conteos: 45, 28, 4; suma comprobada con Python: 77.

### Regresiones adicionales del executor compartido

```bash
scripts/run_tests.sh tests/run_agent/test_tool_executor_contextvar_propagation.py tests/agent/test_tool_executor_checkpoint_paths.py tests/agent/test_inline_tool_executors_memory_args.py --file-retries 0
scripts/run_tests.sh tests/run_agent/test_concurrent_interrupt.py --file-retries 0
```

```text
=== Summary: 3 files, 5 tests passed, 0 failed (100% complete) in 0.7s (24 workers) ===
=== Summary: 1 files, 2 tests passed, 0 failed (100% complete) in 1.1s (24 workers) ===
```

### Lint y whitespace

```bash
.venv/bin/python -m ruff check --no-cache agent/tool_executor.py agent/agent_runtime_helpers.py model_tools.py plugins/platforms/a2a/native_tools.py plugins/platforms/a2a/tools.py plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
git diff --check
```

Ruff: `All checks passed!`; diff check sin diagnósticos. Diff check solo cubre rastreados; Ruff incluye explícitamente archivos nuevos. No se hizo baseline mediante stash ni se alteró implementación para probar una hipótesis.

## Sonda propia: reproducción N1 y negativos

Comando exacto ejecutado, independiente de invocar las funciones de los tests del implementador. Usa selección/assembly/unwrap reales y las dos rutas reales de dispatch con agente mínimo. No es constructor AIAgent completo ni ejecución LLM. El runtime de la sonda y su registry son locales al proceso.

```bash
.venv/bin/python -B -c '
import os,tempfile,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
with tempfile.TemporaryDirectory() as d:
 os.environ["HERMES_HOME"]=d
 os.environ["NATIVE_TEST_BEARER"]="fixture-native-credential"
 import model_tools,toolsets
 import tools.registry as rm
 from tools.registry import ToolRegistry
 from hermes_constants import set_hermes_home_override
 set_hermes_home_override(Path(d))
 from plugins.platforms.a2a import tools
 from plugins.platforms.a2a.outbound import Client,Store
 from agent.tool_executor import _ToolCallRef,_resolve_sequential_dispatch,_unwrap_tool_search_call,_execution_tool_names
 from agent.agent_runtime_helpers import invoke_tool
 from tools.tool_search import assemble_tool_defs,ToolSearchConfig
 r=ToolRegistry(); rm.registry=r; model_tools.registry=r
 config=dict(enabled=True,peer="zuri",runtime="codex",host="zurqui",url="https://zurqui/rpc",token_env="NATIVE_TEST_BEARER")
 def register(): tools.register_tools(SimpleNamespace(get_config=lambda *a:config,register_tool=lambda **kw:r.register(**kw)))
 register()
 def forbidden(*a,**k): raise AssertionError("network/claim/send forbidden")
 Client._open=forbidden; Client.send=forbidden; Store.claim_send=forbidden
 def agent(names): return SimpleNamespace(session_id="owner",valid_tool_names=names,enabled_toolsets=["a2a_outbound"],disabled_toolsets=[],_context_engine_tool_names=set(),_memory_manager=None,quiet_mode=False)
 def dispatch(a,args,executor):
  if executor=="sequential": return json.loads(_resolve_sequential_dispatch(a,_ToolCallRef("a2a_outbound",args,"terminal-not-owner","call",[]),[]).execute(args))
  return json.loads(invoke_tool(a,"a2a_outbound",args,"terminal-not-owner","call",skip_tool_request_middleware=True,skip_tool_execution_middleware=True))
 total=0
 for executor in ("sequential","concurrent"):
  for mode in ("auto","on","off"):
   direct=model_tools.get_tool_definitions(enabled_toolsets=["a2a_outbound"],disabled_toolsets=[],quiet_mode=True,skip_tool_search_assembly=True)
   assembly=assemble_tool_defs(direct,config=ToolSearchConfig(enabled=mode,threshold_pct=5,search_default_limit=5,max_search_limit=20))
   names={t["function"]["name"] for t in assembly.tool_defs}; a=agent(names)
   assert ("a2a_outbound" in names)==(mode=="off")
   args={"action":"prepare","message":"second independent review"}
   name,args,block=_unwrap_tool_search_call(a,"a2a_outbound" if mode=="off" else "tool_call",args if mode=="off" else {"calls":[{"name":"a2a_outbound","arguments":args}]})
   assert block is None and name=="a2a_outbound"
   draft=dispatch(a,args,executor); assert draft["local_state"]=="prepared"
   for action in ("show","resume"): assert dispatch(a,{"action":action,"local_id":draft["local_id"]},executor)==draft
   before={str(p):p.read_bytes() for p in Path(d).rglob("*.sqlite3")}
   sent=dispatch(a,{"action":"send","local_id":draft["local_id"]},executor)
   assert sent["status"]=="blocked" and sent["notification_delivered"] is False
   assert before=={str(p):p.read_bytes() for p in Path(d).rglob("*.sqlite3")}
   print(executor,mode,sorted(names),"prepared/show/resume; send blocked, no claim/network")
   total+=1
   for revoke in ("selection","disabled","bundle","visible","config","registry"):
    b=agent(names.copy()); _,_,block=_unwrap_tool_search_call(b,"tool_call",{"calls":[{"name":"a2a_outbound","arguments":args}]}); assert block is None
    closure=_resolve_sequential_dispatch(b,_ToolCallRef("a2a_outbound",args,"terminal","call",[]),[])
    if revoke=="selection": b.enabled_toolsets=[]
    if revoke=="disabled": b.disabled_toolsets=["a2a_outbound"]
    if revoke=="bundle":
     toolsets.TOOLSETS["review-deny"]={"tools":["a2a_outbound"],"includes":[]}; b.disabled_toolsets=["review-deny"]
    if revoke=="visible": b.valid_tool_names=set()
    if revoke=="config": config["enabled"]=False
    if revoke=="registry": r.deregister("a2a_outbound")
    result=json.loads(closure.execute(args)) if executor=="sequential" else dispatch(b,args,executor)
    assert result.get("status")=="blocked" or "error" in result,(revoke,result)
    config["enabled"]=True
    if revoke=="registry": register()
    total+=1
  for selection in (None,[],["a2a"]):
   for names in ({"tool_call"},{"a2a_outbound"},{"tool_search","tool_describe"}):
    a=agent(names); a.enabled_toolsets=selection
    assert dispatch(a,{"action":"prepare","message":"denied"},executor)["status"]=="blocked"
    total+=1
 print("independent matrices passed:",total)
 for visible in (None,set(),{"terminal","execute_code"},{"tool_call"}):
  a=agent(visible)
  for name in ("terminal","execute_code","web_search","connectors__gmail__list"):
   with patch("agent.tool_executor._tool_search_scoped_names",side_effect=AssertionError("non-A2A resolver called")):
    assert _execution_tool_names(a,name)==(list(visible) if visible else None)
 print("NON-A2A grant equivalence: 16 controls passed")
 print("suite totals:",sum([58,219,105,45,2,6,5,134,2,3,1,3,67,28,12]),sum([45,28,4]))
'
```

Salida real, exit 0:

```text
sequential auto ['tool_call', 'tool_describe', 'tool_search'] prepared/show/resume; send blocked, no claim/network
sequential on ['tool_call', 'tool_describe', 'tool_search'] prepared/show/resume; send blocked, no claim/network
sequential off ['a2a_outbound'] prepared/show/resume; send blocked, no claim/network
concurrent auto ['tool_call', 'tool_describe', 'tool_search'] prepared/show/resume; send blocked, no claim/network
concurrent on ['tool_call', 'tool_describe', 'tool_search'] prepared/show/resume; send blocked, no claim/network
concurrent off ['a2a_outbound'] prepared/show/resume; send blocked, no claim/network
independent matrices passed: 60
NON-A2A grant equivalence: 16 controls passed
suite totals: 690 77
```

Las 60 combinaciones y 16 controles no se suman a pytest. No hubo fallos de entorno ni intentos fallidos en esta revisión. El runner genera cachés de duración/bytecode como parte de su ejecución habitual.

## Puertas reales pendientes, distintas de bloqueantes de esta revisión

El veredicto favorable **no elimina** la necesidad de transportista/estado/código/bearer aislados del UID y herramientas del agente; superficie humana autenticada y no controlable por él; recepción y approve/deny personales de Carlos; binding/TTL/replay y consumo durable atómico. Hashes, DispatchScope y 0700 no proporcionan esa frontera.

Siguen pendientes implementación/version/card reales de Codex/zuri, URL privada exacta y SAN/TLS/bearer, contrato de permisos/continuación y pruebas reales de cortes/reinicios/efecto único. No se contactó al peer, ni se fingió recepción humana o aprobación. Son requisitos para envío protegido/aceptación E2E, **no defectos que invaliden esta entrega explícitamente bloqueada**. Sin autorización de despliegue/arranque, inbound público, cron, jobs o publicación.

Procedimiento reutilizable documentado aquí sin escribir skills fuera del único archivo autorizado: selection → assembly auto/on/off → unwrap → ambos executors; revocar después del unwrap y dentro de la vida de la closure; comprobar disabled compuesto; comparar literalmente la rama no A2A y ejecutar regresiones compartidas. Una lista visible inyectada o una suite verde aislada no prueba el grant diferido real.
