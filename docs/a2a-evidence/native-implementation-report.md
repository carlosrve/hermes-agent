# Implementación nativa A2A — entrega parcial, envío bloqueado

## Resultado y base

**Implementados prepare/show/resume opt-in y send explícitamente bloqueado. No hay aprobación humana ni envío nativo E2E. Revisión independiente de esta capa pendiente.**

- Checkout canónico `/workspace/a2a-integration`, rama `feature/a2a-outbound-recovery`.
- HEAD/base verificado: `1c8aaad2180bbf2fc34f097ab90d069170584ccd`.
- origin `https://github.com/carlosrve/hermes-agent.git`; upstream `https://github.com/NousResearch/hermes-agent.git`.
- Sin commits, staging, push, PR/MR, despliegue, configuración de producción, listeners, cron ni llamadas a zuri. Las pruebas preexistentes usan fixtures loopback; los tests nativos usan transporte en memoria o rechazan cualquier conexión.
- `outbound.py` NO modificado: SHA256 `6efca80535214c90769af2828ef411f0fef6fe0b58ae7545bafc1997601376f0`, igual al tercer review CLI.
- `native_tools.py`: SHA256 `6625dc11fe39a715a7d4a4d7c8f841b18bbe245efcd76c4a4559126384443b84`.

## Artefactos y garantías verificadas

- Nuevo `plugins/platforms/a2a/native_tools.py`: Client/Store existentes; Store por home confiable de profile y hash de sesión (ownership por namespace desde el insert, sin sidecar vulnerable a crash). El modelo no puede elegir propietario/store/endpoint/token/peer/RPC/approved/force.
- `plugins/platforms/a2a/tools.py` registra el sexto tool con gate independiente; `plugin.yaml` lo declara en provides_tools. Los cinco tools legacy conservan gate/comportamiento. Import lazy del cliente POSIX para no romper legacy cuando esa dependencia no está disponible.
- `model_tools.py`: gate localizado para este tool y DispatchScope desde kwargs Python, no argumentos JSON. Exige sesión real, enabled_tools y selección explícita del toolset; disabled prevalece; ningún fallback al catálogo global. La recursión del bridge tool_call conserva esas restricciones.
- Descubrimiento real verifica el ID **`platforms/a2a`**, distinto del nombre `a2a-platform`: `ctx.get_config('outbound')` lee `plugins.entries.platforms/a2a.settings.outbound` y el fallback config existente. Ausente/malformed/disabled falla cerrado incluso despachando directamente. Check no crea Store ni abre sockets. No core/bundles, ni activación legacy/inbound como efecto del opt-in.
- `prepare`: draft exacto, sin red, 64 KiB y sin bearer activo en texto. `show`: snapshot fijo y estados validados, no request/texto/URL/IDs remotos/eventos/metadata/secretos. `resume`: exclusivamente Client.resume/GetTask; sin ID/escritor disponible, observación local. Cross-session/profile rechazados antes de red.
- `send`: `status=blocked`, `reason=human_dispatch_bridge_missing`, `authorization=blocked_bridge_missing`, `notification_delivered=false`. No red, claim, llamada a Client.send, solicitud humana persistida, recepción, decisión ni consumo. Repetir send y YOLO no cambian eso; la BD del draft queda igual.
- `input-required` conserva intervención y nunca significa aprobación. Las pruebas GetTask siembran un ack **solo en fixture**: no simulan que un envío nativo ocurrió ni que Codex continuó un trabajo.
- Tests nuevos `tests/plugins/test_a2a_native_tools.py`, `tests/plugins/test_a2a_native_dispatch.py`; ampliados `test_a2a_schema_registration.py` y `test_a2a_tools_gate.py`.
- Prueba del executor real `agent.tool_executor._resolve_sequential_dispatch`: sesión/grants salen del objeto agent, no de task_id terminal ni JSON; un hijo no ve el draft del padre y grants vacíos bloquean. Objeto agent mínimo de fixture, sin iniciar modelo/gateway.
- execute_code no recibe stub nativo (se ejecutó el generador existente sin ampliar SANDBOX_ALLOWED_TOOLS). Esto no impide terminal/Python de mismo UID.

## RED → GREEN y ajustes de entorno

Logs `native-red-*.log` y `native-green-*.log` preservan fallos y correcciones de registro, prepare/scope, grants/args/send, GetTask, discovery, dependencia POSIX y redacción/estado corrupto. No se borraron las ejecuciones fallidas.

Dos assertions de tests inicialmente pretendían que todo HERMES_HOME permaneciera vacío: conftest crea hermes_test y discovery inicializa directorios Hermes. Se corrigieron para comparar el baseline inicial o únicamente artefactos nativos; no fueron fallos del transporte. El test legacy de conteo fijo se sustituyó por relación con `_TOOLS` más gate nativo independiente, conservando las cinco comprobaciones legacy.

La venv se movió junto al checkout. Se corrigieron exclusivamente shebangs/activación en sus 12 launchers/scripts de `.venv/bin`; sin enlace a la ruta anterior. `pyvenv.cfg:command` y logs anteriores conservan historia. `.venv/bin/pytest --version` devolvió `pytest 9.1.1`; python reportó prefix `/workspace/a2a-integration/.venv`.

El executor real reveló dependencia ausente `requests` (`native-runtime-context.log`). Se instaló **solo en la venv aislada**, usando el pin existente en pyproject:

```bash
.venv/bin/python -m pip install --no-cache-dir requests==2.33.0
```

Exit 0 (`native-test-dependency.log`): requests 2.33.0, charset_normalizer 3.5.1 y urllib3 2.7.0. Sin cambios en pyproject ni dependencias del sistema. La repetición `native-runtime-context-fixed.log` pasó 38 tests.

## Verificación final reproducible

Desde `/workspace/a2a-integration`:

```bash
scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/test_model_tools.py tests/test_model_tools_async_bridge.py --file-retries 0
```

**Exit 0: 15 archivos, 661 tests pasados, 0 fallidos, 19.8 s.** `native-final-suite.log`. Suma extraída y comprobada con Python: `native-test-counts.json`. Incluye la selección previa de 579 tests, 42 nuevos/ampliados y 40 tests adicionales model_tools/async bridge. No es toda la suite Hermes.

```bash
.venv/bin/python -m ruff check --no-cache model_tools.py plugins/platforms/a2a/native_tools.py plugins/platforms/a2a/tools.py plugins/platforms/a2a/outbound.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/fixtures/a2a_outbound_peer.py
git diff --check
```

Ruff: `All checks passed!`, exit 0 (`native-lint.log`). Diff check sin diagnósticos; cubre rastreados. Los archivos nuevos también se pasaron explícitamente a Ruff. Se inspeccionó el diff rastreado y el módulo nuevo completo; AST del módulo nativo: cero llamadas eval/exec/os.system/pickle.load(s)/Client.send. El exec en test ejecuta únicamente el módulo generado localmente por la función existente para comprobar que no hay stub A2A; no es código remoto/modelo. No se encontraron secretos reales en el delta; los bearer de tests son fixtures literales.

## Bloqueantes concretos — no implementar ni afirmar autoridad falsa

1. **Frontera operativa ausente:** DispatchScope, UUID, hash, 0700 y SQLite NO son capabilities no falsificables contra terminal/Python/file del mismo UID. Ese proceso puede importar Client.send, editar código/BD o leer bearer. El CLI manual no se instala como bypass protegido. Requiere broker/transportista con identidad OS/contenedor separada, sin acceso del agente mediante sudo/docker socket/montajes/env/código.
2. **Superficie humana sin seleccionar ni verificar:** elegir una. WebUI requiere código/UI/autenticación/enrollment fuera del control del agente y prueba humana resistente al browser del agente (step-up WebAuthn UP/UV propuesto, no existente aquí); alternativa receptor externo con evento auténtico de proveedor y principal humano verificado. Mismo UID, POST localhost, callback exitoso, cookie/CSRF accesibles al agente o booleano frontend no bastan.
3. **Bridge de despacho inexistente:** mostrar draft/acción exactos, decisión autenticada y durable con binding/profile/sesión/TTL/replay; consumir autorización + claim atómicamente. No se creó job_authorization ni approval_broker porque sin frontera/superficie acreditadas sería falsa seguridad. Send permanece incondicionalmente bloqueado.
4. **Peer zuri no coordinado:** faltan URL privada/SAN/TLS, bearer y repo/versión/cards/contrato real Codex. No ampliar hostname ni usar HTTP por Tailscale. No método A2A approve universal. Permisos remotos y continuaciones requieren contrato real y decisiones humanas separadas.
5. **Aceptación real pendiente:** recepción/approve/deny personal de Carlos, cero efecto antes de consentimiento, continuidad/efecto único después y matriz de reinicios/cortes. Fixtures no acreditan esa aceptación.
6. **Review independiente nuevo → MR → autorización de launch separada.** Esta es evidencia del implementador, no review favorable de su propia capa. El review CLI anterior no se extiende al wrapper. Sin commits/publicación hasta esa revisión.

Actualizados el plan y runbook con ruta canónica y límites; preservada evidencia histórica. Única escritura procedural fuera del proyecto: lecciones genéricas en la referencia A2A del skill hermes-source-fork-integration, autorizada por la excepción de skills.
