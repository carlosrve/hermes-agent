# A2A TURN 51 — GatewayRunner wiring probe

## Alcance

Se añadió una sonda aislada que instancia el `A2AAdapter` real con configuración
fixture y aplica `GatewayRunner._wire_adapter_handlers`. Verifica que los
callbacks de mensaje, fatal, busy-session, autorización, eventos de plataforma,
session store y recuperación de topics quedan instalados en el adapter. También
verifica la autenticación de bearer fixture mediante el `A2ASecurityContext`
inmutable, incluyendo rechazo de un bearer incorrecto.

La prueba no crea `GatewayRunner` completo, sesión gateway, modelo, listener,
`native send`, credenciales productivas ni configuración de producción. La
identidad de la configuración y el token son explícitamente sintéticos.

## Resultado

`.venv/bin/python -m unittest tests.plugins.test_a2a_gateway_wiring_canary -v`
→ 1 passed, 0 failed.

`.venv/bin/python -m unittest tests.plugins.test_a2a_task_store_persistence tests.plugins.test_a2a_inbound_loopback_canary tests.plugins.test_a2a_outbound_operator -q`
→ 9 passed, 0 failed.

`git diff --check` → correcto.

## Límite y siguiente paso

Esta sonda demuestra wiring y gate de transporte, no que el callback real pueda
crear una sesión ni ejecutar el modelo. La ruta de modelo requiere que el
`GatewayRunner` existente suministre loop, session store, handlers y configuración
segura de proveedor/modelo en un harness temporal. No se suplanta ese ciclo de
vida con `object()` ni con `CALLBACK_FIXTURE_REPLY`, y no se ejecuta aquí sin una
configuración de proveedor de prueba verificable.

El follow-up Hermes de Zuri `7fc0b1fe8ea9b3d29c207aa1cb172a2927091386`
(`zuri/turn-50-taskstore-reopen-prune`) queda enlazado para revisión separada;
no se reescribió ni se fusionó en esta rama.
