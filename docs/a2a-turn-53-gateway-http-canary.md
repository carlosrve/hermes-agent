# A2A TURN 53 — canario HTTP aislado del GatewayRunner

## Alcance

Se incorporó `scripts/run_gateway_http_stub_canary.py` como harness de proceso
foreground y loopback. Construye un `GatewayRunner` con `GatewayConfig` y
rutas temporales, registra el `A2AAdapter` en `runner.adapters`, y reutiliza
`GatewayRunner._wire_adapter_handlers` sin sustituir sus gates de admisión por
un callback incondicional. El bearer es únicamente una constante de prueba
local; no se escribe en resultados ni evidencia.

El modelo está explícitamente simulado. El callback cuenta una llamada y
produce `TURN53_SIMULATED_MODEL_REPLY`; esto no acredita un modelo real,
`ObjectiveGrant`, envío nativo protegido ni E2E entre hosts.

## Recorrido probado

El harness abrió solo un listener HTTP en `127.0.0.1` con puerto efímero,
envió `SendStreamingMessage` y extrajo el texto desde `artifactUpdate`. Cerró
el adapter, cerró el TaskStore SQLite y creó un segundo adapter sobre la misma
ruta temporal. `GetTask` recuperó el task completado y el texto desde
`artifacts[].parts[].text`, sin reenviar el mensaje. El resultado exige además
exactamente una llamada al modelo simulado y conserva `simulated: true`.

Comando ejecutado:

    .venv/bin/python scripts/run_gateway_http_stub_canary.py --output /tmp/turn53-canary-result.json

Resultado real: proceso con código 0; `send_state` y `get_state` fueron
`TASK_STATE_COMPLETED`, ambas respuestas fueron
`TURN53_SIMULATED_MODEL_REPLY`, y `model_calls` fue 1. El proceso limpió el
adapter y sus recursos temporales en `finally`; no quedó listener público ni
se modificó gateway, Compose, imagen o producción. La ejecución emitió warnings
operativos no bloqueantes del entorno Hermes, sin cambiar el resultado.

## Límites y siguiente trabajo

La prueba es un canario aislado con fixtures y no es E2E ni una validación de
modelo real. No habilita `native send`, no usa bearer productivo, no lee
configuración productiva y no publica endpoint. La siguiente integración debe
aportar, fuera de este harness, la frontera confiable de `ObjectiveGrant`, la
sesión/autorización de origen y la política para envío protegido; no se debe
inferir ninguna de ellas a partir de este resultado.
