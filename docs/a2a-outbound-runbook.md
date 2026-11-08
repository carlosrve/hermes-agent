# Outbound A2A recuperable: Rafa → zuri (Codex, zurqui)

## Estado y límites de la entrega

**Código experimental en checkout aislado; NO activado ni desplegado.**
Base verificada directamente en `/opt/hermes`:
`1c8aaad2180bbf2fc34f097ab90d069170584ccd`, rama desplegada
`integration/upstream-2026-09-12`. Checkout de trabajo:
`/workspace/a2a-integration`, rama `feature/a2a-outbound-recovery`.
La ruta anterior `/workspace/lfc/a2a-integration` en informes/logs es histórica.
`origin=https://github.com/carlosrve/hermes-agent.git`;
`upstream=https://github.com/NousResearch/hermes-agent.git`.
Sin commits, push, PR/MR ni modificaciones del runtime. Revisión independiente
obligatoria antes de publicar; aprobación de inicio separada antes de activar.

El fundamento previo es el **CLI explícito del módulo**
`python -m plugins.platforms.a2a.outbound`, stdlib Linux/POSIX, sin cambios.
Ahora también existe el tool nativo experimental **`a2a_outbound`**, en toolset
separado homónimo: ausente por defecto, nunca en core/bundles. No se añade
`hermes a2a`, no se activan peers legacy ni listener. La sección «Contrato
implementado» más abajo describe el CLI; **su send no es el send nativo**.

### Contrato nativo parcial — no habilitar para producción

- Config real, verificado por discovery: `plugins.entries.platforms/a2a.settings.outbound`
  (`ctx.get_config`, fallback a `plugins.entries.platforms/a2a.config.outbound`).
  No existe fallback a `config.outbound` global ni a `outbound` top-level. No usar el nombre de
  manifest `a2a-platform` como si fuera su ID de registry.
- Mismos campos de Client, pero **sin `allow_loopback_http`**, ni siquiera false:
  enabled boolean true, peer zuri, runtime codex, host zurqui, URL HTTPS with the
  exact certificate-bound FQDN `zurqui.tuna-gray.ts.net` (a port/path may be
  configured), token_env and timeout opcional acotado. No hay URL real/certificado
  confirmado; the hostname allowlist rejects suffixes and subdomains.
- El caller Python debe proporcionar sesión real no vacía, `enabled_tools` que
  incluya el tool y selección explícita del toolset; disabled prevalece. Ningún
  ID/scope/grant del JSON del modelo es autoridad. Handler directo sin metadata
  de dispatch falla cerrado. No usa `_last_resolved_tool_names` como permiso.
  Con Tool Search diferido, los executors secuencial/concurrente usan el inventario
  autorizado de `_tool_search_scoped_names(agent)` (selección configurada de esa
  sesión antes de assembly), no una unión del registry o de schemas visibles.
  El inventario se consulta dentro de la ejecución; dispatch vuelve a aplicar la
  selección con disabled al final, incluso bundles, y el handler revalida config.
  La corrección de N1 y sus logs están en `a2a-evidence/native-correction-report.md`;
  sigue pendiente una nueva revisión independiente.
- `prepare`: `{action: "prepare", message: "..."}`; cero red, mensaje inmutable
  por API y limitado a 64 KiB; requiere bearer en env para rechazar su inclusión.
- `show/send/resume`: solo action + local_id (32 hex). No approve/force, endpoint,
  token/store/RPC/peer, owner ni continuaciones del modelo.
- Store aislado por home confiable del profile y `a2a-native-<sha256(session_id)>`.
  No importa registros CLI ni agrega ownership después de preparar: namespace
  propietario desde el primer insert. No sirve para controlar terminal del mismo UID.
- `show`: snapshot fijo (local_id, local_state, remote_state, authorization, status),
  sin texto del draft, requests, URL, tokens, IDs remotos, artefactos ni eventos.
  No es todavía la tarjeta humana que debe mostrar el draft exacto.
- `send`: siempre `blocked`, reason `human_dispatch_bridge_missing`,
  authorization `blocked_bridge_missing`, notification_delivered false. **No
  solicita realmente aprobación ni notifica a Carlos; no reclama, envía o consume.**
- `resume`: Client.resume/GetTask exclusivamente; sin task ID o escritor disponible
  solo observación local. No respuesta remota ni continuación automática. Las
  pruebas del wrapper usan ack sembrado explícitamente en fixture, no envío nativo.
- `input-required` y `auth-required` nunca equivalen a consentimiento. El estado
  remoto permanece separado de la autorización local; no hay método A2A approve.
- Errores de transporte/Store devuelven bloqueo genérico sin detalles sensibles.
  Un error de persistencia puede haber dejado un commit; no afirmar rollback.

**Frontera pendiente:** same-UID terminal/Python puede leer env, editar Store/código
 o llamar el CLI. Este wrapper no lo impide ni pretende ser no falsificable.
Antes de enviar protegido, elegir broker aislado + una superficie humana verificada
(§5 del plan), almacenar decisiones y consumir autorización junto al claim en una
sola transacción; validar actor/binding/TTL/replay. No basta un booleano, callback,
YOLO, request_id, cookie accesible al agente o smart approval. Sin esa frontera,
no dar el bearer al proceso agente como si el gate local protegiera la salida.

La venv aislada se reubicó corrigiendo solo las rutas de activación/shebangs en
`.venv/bin`; no symlink al checkout viejo ni cambios de dependencias del sistema.
`pyvenv.cfg:command` conserva la invocación histórica de creación. El runner
canónico ya usa `.venv/bin/python` por ruta absoluta. Logs antiguos se conservan.
Para ejercitar el executor real faltaba `requests`: se instaló exclusivamente en
esta `.venv` el pin del proyecto `requests==2.33.0` (transitivas nuevas:
charset_normalizer 3.5.1 y urllib3 2.7.0). No se cambió pyproject ni el sistema;
`native-test-dependency.log` registra la instalación con `--no-cache-dir`.
Revisión independiente de esta nueva capa y MR pendientes; el review CLI previo
no la acredita. Evidencia: `a2a-evidence/native-implementation-report.md`.

**Bloqueado para aceptación real:** URL privada, certificado, bearer por peer,
AgentCard real y codex-a2a de zuri no estuvieron disponibles. Los tests usan
un fixture HTTP propio; NO prueban persistencia de codex-a2a ni recepción,
aprobación o denegación humana de Carlos.

## Contrato implementado

1. `prepare MESSAGE` crea UUID local/correlación JSON-RPC y `messageId`, guarda
   solicitud completa antes de cualquier envío y devuelve el registro.
2. `send LOCAL_ID` reclama atómicamente `prepared → uncertain` en SQLite antes
   de tocar la red. Solo una instancia puede reclamarlo. No hay reintentos.
3. JSON-RPC 2.0, header `A2A-Version: 1.0`, método `SendStreamingMessage`,
   `params.message.role=ROLE_USER`, Part `{text: ...}`. SSE encapsulado como
   JSON-RPC `result` con un único miembro `task`, `message`, `statusUpdate`
   o `artifactUpdate`. Referencia wire:
   <https://github.com/a2aproject/A2A/blob/main/docs/specification.md>, §9.4.
4. Cada evento válido se guarda sin esperar al fin del stream, incluyendo
   `task_id`, `context_id`, estado remoto y evento/artefacto original. Las
   identidades posteriores no pueden cambiar. Los eventos conservan flags
   `append`/`lastChunk`; no se descargan URIs ni se ejecuta contenido remoto.
5. `resume LOCAL_ID` hace exclusivamente `GetTask` con `params.id` cuando hay
   task ID y no existe otro escritor activo para esa solicitud. Durante un
   `send`/`resume` activo devuelve únicamente la última instantánea durable,
   sin petición remota ni cambio de revisión. Sin task ID tampoco escribe:
   conserva `prepared` (no consume el envío), Message observado o `uncertain`
   para conciliación humana. Nunca reenvía. Repetir `resume` explícitamente
   cuando termine el escritor si se necesita una consulta remota nueva.
6. SQLite `journal_mode=DELETE`, `synchronous=FULL`; commits transaccionales y
   fsync del directorio. Directorio privado 0700, DB creada 0600, rechazo de
   symlink en el destino. Usar disco local, no NFS. Un `flock` no bloqueante
   por solicitud serializa escritores durante toda la operación de red, sin
   mantener transacciones SQLite abiertas. El kernel lo libera al cerrar o
   morir el proceso; nunca borrar los archivos `.lock` durante uso. El contador
   de revisión/CAS sigue rechazando escrituras obsoletas como segunda defensa.
   **Errores de persistencia se propagan:** nunca se convierten en éxito ni
   se ignoran. Tras un error de fsync el commit puede haber ocurrido: no
   reenviar; inspeccionar el registro y conciliar.
7. Los registros y artefactos son datos privados, no instrucciones. La BD
   puede contener textos sensibles del encargo/resultados aunque no incluya
   credenciales del transporte. Aplicar política de acceso, backup y retención
   antes de producción; no hay tarea de limpieza automática.

### Estados separados

| `remote_state` (último estado observado) | `local_state` | Acción |
|---|---|---|
| null, sin envío aún | `prepared` | Envío explícito único autorizado |
| null / submitted / working | `uncertain` | No afirmar fallo ni finalización; `resume` explícito |
| input-required / auth-required | `intervention_required` | Cierra stream; intervención humana, sin respuesta automática |
| completed / failed / canceled / rejected | `observed` | Resultado remoto guardado; no repetir encargo |
| Estado previo conservado, GetTask -32001 | `remote_missing` | Tarea remota no localizada; conciliar, nunca recrear automáticamente |

Se conserva literalmente cada evento remoto; `remote_state` usa el nombre del
enum, también cuando el peer usa su representación entera ProtoJSON. Una desconexión, timeout, error
local o pérdida del task store remoto NO se presenta como `TASK_STATE_FAILED`.
`observed` no significa necesariamente éxito: consultar `remote_state` y
los eventos. Un resultado Message sin task ID queda durable y no requiere
GetTask. Salida CLI 0 significa que la observación quedó registrada, no que
el trabajo remoto terminó ni que Carlos aprobó algo. Salida 2 indica error;
no imprime tokens, cuerpo remoto ni URL en los errores.

### Límites defensivos

- SSE: LF, CR y CRLF; BOM inicial, comentarios/heartbeats, data multilínea,
  fragmentación UTF-8; EOF no sustituye delimitador de evento.
- Línea 64 KiB, evento 1 MiB, stream 8 MiB, 4096 eventos, JSON profundidad 64;
  rechaza claves duplicadas, NaN, UTF-8/JSON inválido y eventos truncados.
- GetTask 1 MiB, registro durable 8 MiB, mensaje saliente 64 KiB.
- Validación recursiva A2A 1.0 de Message/Task/StatusUpdate/ArtifactUpdate antes
  de cambiar estado o correlación: IDs, enums, status, partes/artefactos/historial,
  metadatos y flags. Un evento inválido aborta con error y conserva el último
  registro válido; no procesa un supuesto resultado final ni reenvía.
  `Task.contextId` es opcional en el proto 1.0; en eventos update es obligatorio.
  Message de servidor (`ROLE_AGENT`) requiere contexto según la prosa normativa.
  Se aceptan partes data con cualquier valor JSON, base64 estándar/URL-safe,
  campos opcionales null y formas de lectura ProtoJSON (aliases snake_case y
  enums enteros conocidos); aliases duplicados y enums desconocidos se rechazan.
  Fuente fijada y decisiones de compatibilidad en `a2a-evidence/correction-report.md`.
- Timeout explícito `0 < timeout <= 300` segundos (30 por defecto), sin
  prolongarlo por heartbeats ni cabeceras HTTP lentas. Un temporizador local
  cierra el socket, incluso en framing HTTP bloqueado. No es un job ni un
  mecanismo de reconexión. DNS depende del resolver del SO; configure la
  resolución privada y sus límites antes de producción. TCP/TLS tienen su
  timeout de socket; no se promete una cota estricta de wall-clock para DNS.
- Sin proxies de entorno, redirects, descubrimiento AgentCard, callbacks,
  suscripción, fan-out, cancelación ni respuestas a aprobaciones.
- HTTPS con validación TLS del sistema y hostname `zurqui.tuna-gray.ts.net`
  exclusivamente para el receptor privado. Se rechazan sufijos, subdominios y
  hosts parecidos; la coincidencia no usa wildcard. HTTP únicamente para fixture
  en `127.0.0.1`/`::1`, con opt-in explícito.
- El binding durable incluye peer/runtime/host/URL exactos; si cambian, resume
  se niega antes de la petición. Estos son valores configurados, no una
  certificación de que el servidor remoto realmente ejecuta Codex.
- Bearer solo mediante nombre de variable de entorno, obligatorio y no vacío.
  No se guardan token ni headers. Se rechaza incluir el bearer activo en el
  texto del encargo o recibirlo reflejado en eventos. No es un detector de
  todos los secretos posibles. La rotación del bearer no altera el binding.

## Uso manual después de superar las puertas

**No ejecutar contra zurqui hasta coordinar y aprobar el inicio.** Este ejemplo
es documentación, no configuración creada ni una URL real validada. Crear un
archivo JSON privado fuera del repo, solamente cuando Carlos confirme datos:

```json
{
  "enabled": true,
  "peer": "zuri",
  "runtime": "codex",
  "host": "zurqui",
  "url": "https://zurqui.tuna-gray.ts.net:8443/RUTA_JSONRPC_CONFIRMADA",
  "token_env": "ZURI_A2A_BEARER",
  "timeout": 30,
  "allow_loopback_http": false
}
```

`ZURI_A2A_BEARER` debe llegar por el mecanismo de secretos coordinado, nunca por
chat, argumentos del comando, JSON o Git. Las claves de este JSON pertenecen
**solo a este CLI**, no al config nativo de Hermes. `enabled` debe ser booleano
true; campos desconocidos y secretos literales se rechazan.

Con directorio padre ya existente y privado, desde el checkout aprobado:

```bash
python -m plugins.platforms.a2a.outbound --config /RUTA/peer.json --store /RUTA/estado-a2a prepare 'Encargo inocuo autorizado'
# Guardar el local_id devuelto. Inspeccionar antes del único envío.
python -m plugins.platforms.a2a.outbound --config /RUTA/peer.json --store /RUTA/estado-a2a show LOCAL_ID
python -m plugins.platforms.a2a.outbound --config /RUTA/peer.json --store /RUTA/estado-a2a send LOCAL_ID
# Tras reinicio/corte, únicamente:
python -m plugins.platforms.a2a.outbound --config /RUTA/peer.json --store /RUTA/estado-a2a resume LOCAL_ID
```

No usar un nuevo `prepare` para recuperar un envío incierto: produciría otra
identidad local y otro encargo. El protocolo no proporciona aquí una búsqueda
remota por `messageId` que garantice deduplicación antes del ack. Conciliar con
el operador de zuri usando la correlación durable; si no hay prueba del estado
remoto, mantener el bloqueo. No editar a mano la BD para volver a `prepared`.

## Auditoría de aprobaciones existentes (solo lectura)

Referencias al **commit base**, no una demostración E2E:

- `tools/approval_gateway_wait.py:105-167`: `_await_gateway_decision` encola
  una entrada en memoria, notifica por callback y espera el evento de decisión;
  si falla la notificación devuelve no resuelto. La espera interrumpida deniega.
- `tools/approval.py:139-171`: `resolve_gateway_approval` resuelve por sesión
  y opcional `request_id`, coloca elección/motivo y señala el evento.
  `174-205` permite listar/ack/reproyectar pendientes **del proceso vivo**.
  Esto NO es persistencia de aprobaciones o tareas de codex-a2a.
- `gateway/run_turn_runner.py:1295` y siguientes: `_approval_notify_sync`
  entrega tarjetas `send_exec_approval` o texto con instrucciones `/approve`.
- `gateway/slash_commands.py:1134-1178`: `/approve` y `/deny` llaman al resolver
  para la sesión, y la denegación puede incluir motivo.
- `tui_gateway/server.py:682-688,931`: emite `approval.request` mediante la
  notificación registrada; la superficie TUI/Desktop responde por su ruta
  `approval.respond` (`tui_gateway/methods_prompt.py`).

Este cambio **no conecta** un `TASK_STATE_INPUT_REQUIRED` remoto a esa cola.
No existe en este delta un puente Carlos ↔ aprobación de Codex. El estado se
persiste, se devuelve y se detiene; el operador debe usar la superficie humana
real de zuri. Probar mocks de `input-required` NO valida recepción ni approve/
deny de Carlos. Tampoco se modificó `approvals.mode`, YOLO, handlers, gateway
ni callbacks. El bearer autentica transporte; no autoriza acciones remotas.

## Puertas manuales obligatorias (todas pendientes para peer real)

- [ ] Revisión independiente del diff, tests y límites; commit/publicación/MR
      solo tras revisión; despliegue solo por flujo aprobado.
- [ ] Aprobación separada de Carlos para iniciar la prueba privada. Confirmar
      URL JSONRPC, versión 1.0, AgentCard y runtime Codex en zurqui; verificar
      resolución privada, TLS y alcance de firewall sin publicar listeners.
      Inspeccionar AgentCard sin reenviar bearer a URLs que esta anuncie.
- [ ] Verificar bearer exclusivo de Rafa, rechazo de credencial incorrecta y
      peer ajeno; no almacenar ni compartir secretos en la evidencia.
- [ ] Encargo inocuo real: `prepare`, envío único, correlaciones verificadas
      a ambos lados, artefacto final y GetTask.
- [ ] Cortar cliente antes y después del ack; comprobar cero SendMessage/
      SendStreamingMessage duplicados y recuperación exclusivamente GetTask.
- [ ] Reiniciar servidor Codex durante working. Distinguir task store durable
      vs perdido; documentar artefactos/conversación/task store por separado.
- [ ] **Carlos recibe realmente la solicitud en su superficie identificada**:
      mostrar task/context/local IDs, acción propuesta, origen zuri y estado.
      Confirmar visualmente/por recibo humano; no basta log de callback.
- [ ] **Caso aprobar:** Carlos aprueba personalmente un efecto de prueba
      inocuo; demostrar que no ocurrió antes y ocurrió una sola vez después.
      Registrar evidencia de recepción, decisión correlacionada y resultado.
- [ ] **Caso denegar:** nueva tarea de prueba, Carlos deniega personalmente;
      demostrar que el efecto no ocurrió y el resultado refleja la denegación.
- [ ] **Sin respuesta/auth-required:** permanece bloqueado; Rafa no contesta
      por Carlos, no cambia políticas, no inyecta secretos y no reenvía encargo.
- [ ] Validar pérdida/reinicio de la superficie de aprobación y caducidad:
      no suponer que una cola en memoria sobrevive un reinicio.
- [ ] Revisión final de evidencias y autorización expresa para activar uso
      limitado. Sin cron, jobs automáticos, push callbacks ni inbound Hermes.

Si cualquiera falla: no activar. Un fixture verde no sustituye estas puertas.
Ver `a2a-evidence/README.md` para resultados reproducibles y fallos de entorno.
