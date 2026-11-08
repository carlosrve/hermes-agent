# Plan mínimo: A2A nativo + autorización humana

**Estado actual: implementación nativa parcial offline; send bloqueado. Sin lanzamiento.**

Ruta canónica actual: `/workspace/a2a-integration`, rama
`feature/a2a-outbound-recovery`, base/HEAD `1c8aaad2180bbf2fc34f097ab90d069170584ccd`.
Las referencias posteriores a `/workspace/lfc/a2a-integration` y el cierre por cuota
son **evidencia histórica**, no rutas/instrucciones vigentes. El límite fue cuota
OpenAI administrada por Carlos, no reinicio de conversación.

Implementados `native_tools.py`, descubrimiento/schema opt-in, gate localizado en
`model_tools.py` y pruebas nativas. `prepare/show` locales; `resume` exclusivamente
GetTask u observación local; `send` responde `blocked` /
`human_dispatch_bridge_missing`, **sin red, claim, solicitud humana persistida,
notificación ni decisión inventada**. No hay ruta que consuma permisos ni llame
`Client.send`. No se crearon job_authorization, broker o superficie humana.
Informe y comandos reales: `a2a-evidence/native-implementation-report.md`.

Corrección del hook de configuración: `ctx.plugin_id` deriva de `manifest.key`.
El descubrimiento real del bundled plugin resuelve **`platforms/a2a`**; no
`a2a-platform` (ese es el nombre del manifest). `ctx.get_config('outbound')` lee
`plugins.entries.platforms/a2a.settings.outbound`, con fallback nativo al subárbol
`plugins.entries.platforms/a2a.config.outbound` (no global). Configuración ausente/deshabilitada/malformada cierra el handler.

No existe frontera no falsificable en el mismo UID: DispatchScope solo conserva
metadata suministrada por Python confiable; no es una capability criptográfica.
Particionar Store por home de profile + hash de sesión evita acceso cruzado por
el tool, no por terminal/file/Python del mismo usuario. El CLI experimental sigue
sin cambios y puede enviar si un proceso dispone del bearer. **No instalarlo con
bearer accesible al agente y afirmar que está protegido por aprobación nativa.**
Las alternativas de aislamiento de §5 siguen siendo bloqueantes operativos:
A requiere UI/código/config/authenticator/enrollment fuera del control del agente;
B requiere receptor autenticado de proveedor y principal humano fuera del UID;
un broker con el mismo UID, sudo, docker socket o montajes accesibles no lo logra.
No se implementa esa parte insegura ni se acredita ninguna de las dos opciones.

## Registro histórico de la investigación inicial

Investigación concluida entonces; sin implementación ni lanzamiento en esa entrega.
El resto preserva el diseño y su evidencia original; la primera entrega ejecutada
adopta explícitamente la alternativa de §9 (send bloqueado).

## 1. Base y evidencia verificadas

- Repo `/workspace/lfc/a2a-integration`, rama `feature/a2a-outbound-recovery`, HEAD `1c8aaad2180bbf2fc34f097ab90d069170584ccd`; remotes `carlosrve/hermes-agent` y `NousResearch/hermes-agent`.
- Leídos `docs/a2a-outbound-runbook.md`, `docs/a2a-evidence/third-independent-review.md`, `plugins/platforms/a2a/outbound.py` y hooks abajo. La revisión favorable cubre **CLI manual**. Los 579 tests pertenecen a esa revisión; los 277 del cliente son evidencia comunicada por el padre, no ejecuciones nuevas de esta investigación.
- WebUI descubierto e inspeccionado solo como fuente: `/workspace/hermes-webui-pr-6836-current`, HEAD `12453f00d859bc6a7c8610826d84844bd87a1491`, fork `carlosrve/hermes-webui`, upstream `nesquena/hermes-webui`. **No se verificó que sea la versión desplegada para Carlos.** No se editó allí ni en `/opt/hermes`.
- Cargados skills hermes-agent, hermes-source-fork-integration y referencia A2A, requesting-code-review y plan. Docs oficiales de seguridad consultados: <https://hermes-agent.nousresearch.com/docs/user-guide/security/>. Developer-guide raíz devolvió 404; los hooks se comprobaron en fuente local.

## 2. Un tool, cuatro acciones, opt-in independiente

Proponer **`a2a_outbound`**, toolset separado del mismo nombre, con `action=prepare|send|show|resume`, `message` solo para prepare y `local_id` para las otras. Validación estricta también en Python. Sin argumentos URL, token, store, peer arbitrario, método RPC, `approved`, `force`, approve/deny ni payload de continuación.

| Acción | Contrato |
|---|---|
| prepare | Draft inmutable y vinculado al profile/sesión confiable; cero red. `Client.prepare` devuelve local_id: cargar después con `Store.load`. Actualmente exige token presente para rechazar su inclusión en el texto. |
| show | Snapshot propio y acotado; estado remoto, autorización y entrega separados. Cero red, sin devolver DB/eventos completos de hasta 8 MiB. |
| send | Sin consentimiento: persistir/reutilizar solicitud humana `dispatch_job`, proyectarla y devolver `awaiting_human`, sin contactar peer. Con autorización válida: consumirla atómicamente con el claim y enviar una vez. Denegación/caducidad/notificación fallida bloquean. |
| resume | **GetTask-only** u observación local cuando no hay ID/escritor disponible. No significa aprobar, conversar, reanudar ejecución Codex ni reenviar. |

El clic autoriza, no arranca un job de fondo: un send explícito posterior consume la decisión. No espera indefinida, cron, callbacks inbound, fan-out, reconexión automática o descubrimiento arbitrario.

### Hooks mínimos reales

- `plugins/platforms/a2a/plugin.yaml:29–38`, `provides_tools`: declarar el nuevo nombre permite descubrimiento CLI/TUI; no habilita por sí solo.
- `plugins/platforms/a2a/tools.py:355–363`, `register_tools(ctx)`: registrar wrapper nuevo; conservar los cinco legacy y sus gates. `__init__.py:79–98` ya permite cliente sin activar inbound.
- `hermes_cli/plugins.py:253`, `PluginContext.get_config`; `:456–498`, `register_tool`: config scoped y registro público con `check_fn`. Proponer subárbol `config.outbound`, ausente = disabled; resolver ID real del plugin (manifest name `a2a-platform`), no adivinarlo por directorio.
- `toolsets.py:269–300,400`: toolsets del registry resueltos dinámicamente. **No añadir a `_HERMES_CORE_TOOLS` ni bundles predeterminados.**
- `model_tools.py:313–334`: disabled se resta al final; `:858–929` dispatch/bridge. `tools/registry.py:810–834` **no revalida check_fn al despachar**. Handler y frontera autorizadora deben revalidar config/grants/scope; ocultar esquema no es seguridad.
- `outbound.py:267,384–441,452–549`: Client/Store reutilizables; conservar flock, CAS, claim durable antes de red, fsync y no-reenvío.

Nueva configuración **propuesta, aún inexistente**: enabled false por ausencia, único peer `zuri`, runtime `codex`, host lógico `zurqui`, URL exacta coordinada, `token_env` con nombre de variable (p. ej. `ZURI_A2A_BEARER`), timeout acotado. Store derivado de `get_hermes_home()`, no args del modelo. `check_fn` sin sockets ni creación de BD; fallo = false. Exposición requiere configuración explícita y selección de toolset de la superficie. A2A_PORT, inbound o `a2a_agents` no abren este gate.

El legacy `tools.py` acepta URL directa, descubre AgentCard y usa SendMessage: **no reutilizar `_resolve_peer`, `_send_task`, `_a2a_tools_available` ni su consejo de volver a llamar a2a_call ante input-required**. No habilitar esos tools como efecto de este opt-in.

Añadir comprobación localizada para el nuevo tool en dispatch con grants del caller real (`enabled_tools/toolsets`, disabled, profile/sesión), y contexto confiable hasta el wrapper. Scope ausente bloquea send. Probar también handler directo, tool_call, execute_code y subagentes; no aceptar owner/grant en args. No ampliar `SANDBOX_ALLOWED_TOOLS` en primera entrega.

## 3. Transporte: HTTPS privado, sin excepciones Tailscale

`Client.__init__:244–265` exige HTTPS y hostname **zurqui**. HTTP solo `127.0.0.1`/`::1` opt-in de fixture. `_open:281–338` usa TLS del sistema y no sigue redirects/proxies de entorno.

- **No permitir HTTP remoto por ser Tailscale**, ni ampliar loopback a 100.64/10, redes privadas o MagicDNS; nunca desactivar TLS.
- Si el certificado necesita FQDN de tailnet, coordinar nombre/SAN exactos y ampliar allowlist mediante cambio mínimo revisado, sin comodines. No cambiar binding de tareas activas silenciosamente.
- Bearer exclusivo por peer desde entorno del transportista autorizado; nunca token literal en config/Git/args/logs/DB. Rotación no cambia identidad estable.
- **Peer autenticado ≠ encargo autorizado.** Bearer tampoco demuestra qué runtime ejecuta el servidor.

## 4. Aprobaciones reales existentes: reutilizar presentación, no autoridad genérica

### Hermes

- `tools/approval.py:961–986`, `request_tool_approval`: gate real para hooks de plugins, pero comparte once/session/always, allowlists y políticas de comandos; **no es consentimiento exclusivo por job**.
- `tools/approval_gateway_wait.py:105–167`: cola en memoria, notificación y espera, coalescing por command/patterns; no persistencia de aprobaciones tras restart.
- `tools/approval.py:139–205`: resolver FIFO/all/request_id y list/ack; no prueba por sí mismo autor humano.
- `gateway/run_turn_runner.py`, `_approval_notify_sync`: proyección `send_exec_approval`/texto. `gateway/slash_commands.py:1134–1178`: /approve y /deny incluyen all/session/always; no adoptar esas variantes para A2A.
- `tui_gateway/server.py:634–688,931`: evento `approval.request`; `tui_gateway/methods_prompt.py:1134–1198`: pending/received/respond. Su fallback global por request_id no debe copiarse sin ownership/profile.

### WebUI de referencia

- `api/streaming.py:9679–9717`: registra notify, mirror y SSE `approval`; `api/route_approvals.py`: colas/mirrors/subscribers.
- `api/routes.py:14584–14590,16705–16706`: pending/stream/respond. `_handle_approval_respond:26742...` admite once/session/always/deny, rama YOLO y relay con approval_id/run_id/mirror_token.
- `static/messages.js`: showApprovalForSession/showApprovalCard y captura de owner de tarjeta.
- `api/auth.py:1094...`, check_auth permite cuando auth está apagada. `api/routes.py:5895–5910`, `_check_csrf` exime clientes sin Origin/Referer. **Un POST local, request_id o callback exitoso no acredita humano.**

Separar autorización para enviar/revelar el encargo, pregunta conversacional y permiso específico remoto. Los guards de comandos peligrosos permanecen intactos, pero no autorizan todas las mutaciones/API/jobs remotos.

## 5. Diseño de decisión humana no falsificable

### Frontera necesaria y bloqueo actual

Si el agente conserva terminal/Python con el mismo UID, puede importar resolver, editar BD/código o leer bearer y llamar al peer. Ni un prompt, `pre_tool_call`, UUID público ni cookie accesible al browser del agente lo impiden.

**Opción recomendada:** broker estrecho para un único peer, aislado por identidad OS/contenedor, dueño del store de autorización, código/configuración y bearer en su propio entorno. API interna fija prepare/show/send/resume; nada de shell/URL/RPC arbitrarios. El agente no dispone del token ni puede modificar esa frontera mediante sudo/docker socket/montajes. CLI experimental directo no queda instalado como bypass con token accesible. Si no se garantiza ese aislamiento, **no afirmar autorización no falsificable ni habilitar send protegido**.

No es un motor de workflows ni un listener A2A nuevo: es la frontera específica necesaria para proteger decisión y transporte. Canales de petición del agente y decisión humana tienen autoridad distinta.

### Elegir una sola superficie

**A. WebUI Carlos:** tarjeta/endpoints específicos A2A, fuera de `/api/approval/respond`/YOLO. Auth obligatoria aunque el producto general permita modo sin auth; principal Carlos y ownership/profile derivados del servidor; Origin exacto y CSRF obligatorio, rechazando headers ausentes. No aceptar bearer del peer o credenciales de automatización como humano.

Si browser/computer tools pueden controlar esa sesión, cookies+CSRF no bastan: añadir step-up **WebAuthn con UP/UV**, challenge vinculado a solicitud exacta y elección, origin/RP ID/credencial de Carlos verificados por broker/plano confiable. Clave privada y enrollment/reset fuera del agente. **WebAuthn es propuesta, no hook existente verificado.** Separar también código/UI/configuración: un autenticador no salva una UI que el agente puede sustituir. No aceptar booleano `human=true` del frontend.

**B. Superficie establecida aislada:** receptor externo al UID del agente que valida evento auténtico del proveedor, usuario Carlos, conversación, mensaje/request exactos y botón. Nunca texto citado, mensaje de bot/modelo o /approve incrustado en contenido A2A. Reutilizar hooks gateway/TUI para presentación solo si se demuestra esa frontera; hoy no se acreditó una superficie configurada así para Carlos. Elegir B evita añadir autenticación paralela si ya existe un canal confiable.

### Binding, recepción, replay y persistencia

Registro duradero: approval_id aleatorio, tipo `dispatch_job|remote_permission`, owner/profile/sesión confiables; binding peer/runtime/host/URL y versión de contrato; local_id/messageId/RPC ID; hash canónico del payload/acción/scope exactos; task/context/request de interrupción cuando existan; revisión, nonce/challenge, TTL, receipt, decisión/actor/prueba y fase de entrega.

Antes del envío task/context son null: aprobar el draft identificado, no inventar IDs. Ack fija identidades una vez. Permiso remoto requiere el binding real task/context/acción; falta de datos bloquea. Hash calculado por código sobre JSON finito canónico, no resumen LLM.

Estados: `pending → received → approved|denied|expired`; aprobación de dispatch pasa a consumed. **Consumo + prepared→uncertain en una sola transacción** del store, con CAS/flock; no permiso consumido en otra DB sin reclamo coordinado. Para respuesta remota separar `not_sent→uncertain→acknowledged` de ejecución observada.

- Receipt del cliente autenticado acredita render/recepción técnica, no lectura o aprobación humana; aceptación exige confirmación de Carlos.
- Rechazar replay, nonce/TTL/revisión viejos, owner ajeno, decisiones dobles/opuestas y payload/binding cambiado. Un solo ganador transaccional.
- Nada de all/session/always, YOLO, smart/unattended-approve, coalescing entre jobs ni aprobación permanente heredada.
- Denial no es timeout y no vuelve a preguntar automáticamente. Crash tras consumo conserva incertidumbre, nunca restituye permiso/reenvía. Restart no convierte received en approved.
- Denegar dispatch = cero envío. Denegar permiso remoto = bloqueo y rechazo específico solo con contrato; «Carlos denegó» no equivale a «Codex recibió rechazo».

## 6. Contrato público Codex investigado: opción concreta, peer desconocido

Existen al menos proyectos TypeScript `MyPrototypeWhat/codex-a2a` y Python `liujuanjuan1984/codex-a2a`. **No se sabe cuál/version corre en zuri.** Se fijó main público del Python a `8752104b0badd36956d2e4168dd939ff07a0a1d4` y se inspeccionó documentación y fuente en memoria, sin peer real:

- [guide.md](https://github.com/liujuanjuan1984/codex-a2a/blob/8752104b0badd36956d2e4168dd939ff07a0a1d4/docs/guide.md), sección Interrupt Callback.
- [extension-specifications.md](https://github.com/liujuanjuan1984/codex-a2a/blob/8752104b0badd36956d2e4168dd939ff07a0a1d4/docs/extension-specifications.md) y [compatibility.md](https://github.com/liujuanjuan1984/codex-a2a/blob/8752104b0badd36956d2e4168dd939ff07a0a1d4/docs/compatibility.md).
- Fuente bajo ese SHA: `src/codex_a2a/jsonrpc/interrupts.py`, `interrupt_lifecycle.py` y `upstream/interrupt_bridge.py`.

Ese proyecto documenta `metadata.shared.interrupt`, phase asked/resolved, extensión `urn:codex-a2a:extension:interactive-interrupt:v1` y recuperación `codex.interrupts.list`:

| Señal | Interpretación segura |
|---|---|
| Solo input-required o texto «approve» | Intervención no clasificada; no permiso ni respuesta automática. |
| Pregunta conversacional | Entrada faltante, no autorización; primera versión solo muestra. |
| Tipo permission validado y contrato descubierto | Método de esa extensión `a2a.interrupt.permission.reply`, request_id y reply once/always/reject. Puente futuro admitiría **solo once/reject**, con decisión humana. |
| question | `.question.reply` con answers / `.question.reject`; no confundir con permiso. |
| permissions / elicitation | Contratos distintos de subset/scope o accept/decline/cancel/content; fuera de primera entrega. |
| auth-required | Intervención de credenciales, no autorización para mandar secrets. |

Estos métodos **no son A2A core universal**. Allí callback es respuesta outbound al endpoint del peer, no requiere abrir callbacks inbound Hermes. Contratos detallados se descubren en extended AgentCard; no inventar header de activación ni método genérico approve.

La fuente valida tipo/TTL y owner condicional al binding disponible. Restore repone handles; `_reply_to_server_request` envía al rpc_request_id upstream y después descarta pendiente. **No demuestra que un Codex reiniciado conserve aquella petición viva**, ni exactly-once de efectos ante respuesta incierta.

Antes de implementar puente: coordinar repo/version, cards/esquemas, metadata, request/task/context/thread/turn mapping, TTL, owner, replay/idempotencia, resultado de rechazo y observación/continuación. El cliente actual cierra stream al input-required: si metadata llega después, acordar recuperación o cambio revisado; no asumir GetTask contiene prompts. Hasta disponer del contrato real, solo observación/superficie nativa humana de zuri. Resume sigue GetTask-only. Callback ok no prueba continuación: verificar mismo turno/tarea y efecto posterior.

## 7. Implementación futura, archivos y tests

Cada tarea: RED → mínimo código → GREEN/regresiones → revisión independiente. No ejecutar/publicar automáticamente por este plan.

1. Crear `plugins/platforms/a2a/native_tools.py`; cablear `tools.py:register_tools` y `plugin.yaml:provides_tools`. Tests nuevos `tests/plugins/test_a2a_native_tools.py`; ampliar `test_a2a_schema_registration.py` y `test_a2a_tools_gate.py`, conservando cinco gates legacy y sexto independiente.
2. Gate de ejecución localizado en `model_tools.py` + wrapper. Nuevo `tests/plugins/test_a2a_native_dispatch.py`: disabled, config stale, grants ausentes, scope/profile, tool_call/directo/execute_code y subagente/unattended.
3. Crear `plugins/platforms/a2a/job_authorization.py`; ampliar claim del Store para consumo atómico. Nuevo `tests/plugins/test_a2a_job_authorization.py`: SQLite real, CAS/replay/TTL/carreras y fallos commit/fsync. Modo protegido sin bypass CLI.
4. Frontera propuesta `plugins/platforms/a2a/approval_broker.py` y `tests/plugins/test_a2a_approval_boundary.py`: proceso del agente sin acceso a token/DB/código/prueba humana. Aislamiento operativo pendiente de revisión/autorización, no configurar ahora.
5. **Una superficie**: opción WebUI, proponer `api/route_a2a_approvals.py`, `static/a2a-approvals.js`, cableado limitado en routes/carga frontend; endpoints nuevos `/api/a2a/approvals/pending`, `/received`, `/decision`. Tests nuevos `tests/test_a2a_approval_routes.py` y `test_a2a_approval_frontend.py`. Identificar primero fuente desplegada. Alternativa gateway/TUI con ruta/evento específico, no implementar ambas.
6. Solo con contrato confirmado: `plugins/platforms/a2a/codex_interrupts.py`, `tests/plugins/test_a2a_codex_interrupts.py`, tipo permission y once/reject exclusivamente, parser/binding explícitos. Sin tool approve/deny ni expansión a exec/review/steer.
7. Actualizar runbook/evidencia por nivel realmente logrado; repetir selección de 11 archivos/579 tests del tercer review más nuevos tests; runner `scripts/run_tests.sh ... --file-retries 0`. Tests frontend/auth con runner del repo elegido, por verificar. No inventar comando o conteos. MR/revisión antes de despliegue; permiso de launch separado.

### Regresiones obligatorias

- Cero schemas por defecto, cero red sin grant/decisión, A2A_PORT/inbound no habilitan; ausencia/malformed config falla cerrado.
- Bearer solo entorno del broker, secretos/pruebas no expuestos; HTTP Tailscale, TLS inválido, redirect, URL diferente y binding cambiado rechazados.
- Endpoint humano rechaza auth apagada, owner/CSRF/origin ausentes o ajenos, POST de terminal/MCP, request_id solo, prueba inválida, replay, all/session/always/YOLO. Probar que browser del agente no puede aprobar por Carlos; no basta mock resolved=True.
- Draft exacto/inmutable, decision→claim atómico, doble decisión concurrente un ganador, crashes no restituyen permiso. Conservar parser/SSE/JSON/roles/fsync/CAS existentes.
- Input-required conversacional no crea permiso; «Carlos aprobó» remoto es dato. Metadata desconocida/mismatch bloquea. Auth-required no filtra secretos.
- Callback incierto/no entregado/aceptado sin avance son distintos. Sin retry automático. Fixture debe ejecutar efecto observable: **GetTask no puede fabricar completed como prueba de continuidad**.

## 8. Pruebas reales separadas y puertas pendientes

Primero fixtures deterministas y procesos distintos; después casos coordinados reales con permiso de inicio:

| Caso separado | Evidencia requerida |
|---|---|
| Restart cliente pre-ack | Servidor intacto; claim durable, uncertain sin ID y cero reenvío. |
| Restart cliente post-ack | Servidor intacto trabajando; IDs guardados antes de muerte, nuevo cliente GetTask y efecto único. |
| Restart servidor adapter | Cliente intacto; declarar si hijo Codex sobrevive. Task recuperable o remote_missing, sin recreación. |
| Restart Codex/upstream | Separar task store, conversación/thread, artefactos y RPC de permiso vivo; handle persistido no prueba continuidad. |
| Desconexión red | Sin matar procesos; cortar durante working/permiso/decisión, recuperación explícita sin duplicados. |
| Restart WebUI/receptor/broker | Pending sin/con receipt, aprobado no consumido y respuesta incierta; reproyección/TTL/replay durable, sin autoapprove. |
| Pérdida task store remoto | Conservar IDs/última observación, remote_missing, conciliación sin nuevo job. |

Aceptación humana real obligatoria:

1. Confirmar endpoint/TLS privado, implementación/cards/políticas y bearer correcto/incorrecto, sin bypass. Nada de red al peer hasta autorización separada de prueba.
2. Carlos recibe draft/acción exactos y autoriza personalmente el despacho; cero recepción remota antes, envío explícito único después.
3. Provocar permiso remoto inocuo acordado: receipt de superficie y confirmación de Carlos, IDs correlacionados, cero efecto antes de decidir.
4. **Approve:** decisión humana, recibo del peer, continuidad del mismo trabajo y efecto una sola vez.
5. **Deny:** nueva prueba autorizada, decisión humana, rechazo recibido y ausencia del efecto; no confundir denegación local con entrega remota.
6. Sin respuesta/TTL/auth-required/replay/cortes bloquean. Completar matriz de reinicios independiente y revisión de evidencias sin secretos.
7. MR/revisión y autorización final de activación limitada; sin inbound Hermes, públicos, cron, push ni jobs automáticos.

## 9. Punto de parada / bloqueantes

**Verificado:** hooks nativos mínimos y mecanismos existentes de presentación/respuesta; se puede construir offline wrapper, gates y pruebas de no-envío.

**Pendiente y bloqueante:** superficie efectiva/identidad humana de Carlos; aislamiento de herramientas frente a token/estado/código/sesión humana; opción de prueba humana; URL/certificado y contrato real zuri; receipt/approve/deny/continuación y reinicios reales. No hay integración E2E demostrada.

Si no se acepta cerrar la frontera en esta fase: alternativa honesta es prepare/show/resume opt-in y **send bloqueado**, manteniendo envío/permisos en superficie humana externa verificada. Es entrega parcial explícita, no integración de aprobación terminada.

Por límite de cuota se cierra aquí. Reanudar desde este archivo y resolver bloqueantes antes de ampliar alcance. No se guardó skill ni se modificaron otros archivos para respetar la escritura única autorizada.
