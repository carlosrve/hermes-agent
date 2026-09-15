# Rafa TURN 65 — seam opt-in para callback de aprobación A2A

## Alcance

Se añadió en `tui_gateway/methods_prompt.py` el seam opt-in
`build_a2a_approval_event`. No modifica el handler heredado `approval.respond` ni
su fallback de reconnect Desktop/CLI. El seam solamente construye un evento no
resolvente cuando el caller entrega explícitamente `a2a_event=true`.

La autorización de entrada exige simultáneamente:

- identidad server-stamped no interna en `transport.auth_identity`, reutilizando
  `_is_authenticated_identity` del guard browser-control;
- pertenencia por identidad de objeto al transporte de la sesión, incluyendo
  membresía en `FanoutTransport`;
- `session_key` y `request_id` no vacíos, con el request presente en la cola de
  esa sesión exacta;
- ausencia del parámetro `all`.

El evento solo contiene `session_id`, `request_id`, `callback_required=true` y
`human_decision=false`. No copia `choice`, `approval_id`, `decision` ni otros
campos del worker, no escanea otras sesiones por `request_id`, no llama a
`resolve_gateway_approval` y no fabrica un `DecisionReceipt`. La integración de
un callback confiable y la decisión humana quedan pendientes.

## Pruebas reales

Desde el checkout Hermes y rama de esta entrega:

    python3 -m unittest tests.test_a2a_approval_seam -v

    Ran 4 tests — OK

Los cuatro casos cubren evento legítimo sin resolución de cola, sesión/request
ajenos, transporte/profile no autorizado y `all`, además de opt-in explícito y
redacción de campos de aprobación del worker.

    git diff --check

Resultado: correcto.

No se ejecutó la suite `test_tui_gateway_server` porque este checkout no tiene
instalado `pytest` (el import falla antes de ejecutar tests); no se sustituye esa
prueba por una afirmación. No se invocó aprobación humana, no se leyeron
secretos/env/payloads, no se inició listener, y no se tocó Compose, modelo,
native send, main ni producción.

## Límites

La identidad es fixture en las pruebas. El seam no es autenticación humana,
DecisionReceipt durable, broker aislado del worker, E2E, RPC A2A ni garantía de
exactly-once. El handler heredado conserva su fallback por compatibilidad; no
debe usarse para excepciones A2A hasta integrar este seam con un callback
server-side confiable.
