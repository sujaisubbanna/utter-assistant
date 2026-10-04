---
title: "Confianza y seguridad"
description: "El modelo de seguridad de Utter: etiquetado de procedencia, «el contenido no confiable selecciona, nunca crea», confirmación con argumentos, capacidades peligrosas desactivadas por defecto y permisos de los complementos."
banner:
  content: 'Traducción automática sin revisar. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">Cómo contribuir a la traducción</a>.'
---

Utter puede pulsar teclas, hacer clic, abrir URL y, si se lo permites, escribir en una terminal. También lee
tu pantalla. El modelo de seguridad existe para que lo segundo nunca pueda dirigir lo primero sin
tu consentimiento.

El **runner es la frontera de confianza**. Aplica la política; los complementos y su salida son
**no confiables**, y también lo es todo lo que se lee de la pantalla.

## Etiquetado de procedencia

Cada valor que puede influir en una acción lleva una etiqueta de procedencia:

| Procedencia | Origen | Confianza |
|---|---|---|
| `user` | tu enunciado, entrada explícita en la aplicación de ajustes | **confiable** |
| `screen` | el árbol de accesibilidad, OCR, títulos de ventanas, el portapapeles, contenido web | **no confiable** |

## Selecciona, nunca crea {#select-never-author}

El contenido no confiable **solo puede seleccionar entre candidatos precalculados**. **Nunca puede crear nuevos
argumentos**. En concreto:

- La cabeza de decisión restringida (`llm.choose`) es **no opcional** en cualquier ruta guiada por modelo. El
  modelo elige una letra de una lista que Utter ha construido; no escribe la acción.
- Una petición cuyos argumentos concretos derivan de la procedencia `screen` la rechaza la política con
  el error `-32006` antes de llamar a ningún complemento.
- Los títulos se truncan y se sanean. El texto de la pantalla nunca se convierte en un comando de terminal ni en un
  esquema `open_url` arbitrario.

Esto es lo que hace inofensivos una página web maliciosa, un título de ventana astuto o un portapapeles envenenado:
como mucho pueden empujar a Utter hacia una de las opciones que ya había decidido que eran aceptables.

**El objetivo de la aplicación** sigue la misma regla. Cuando dices `codex type ok`, el nombre de la aplicación es tu
intención, los `app_ids` del perfil están precalculados y la lista de ventanas del compositor en vivo no es confiable
— solo puede **seleccionar** sobre qué ventana recae la acción, nunca proporcionar texto o un comando.
`close <app>` requiere confirmación, y los argumentos derivados de `screen` siguen rechazándose con
`-32006`.

## Confirmación

La confirmación la **aplica el runner y lleva argumentos**. Utter muestra la URL, el comando o el objetivo
**concretos** antes de actuar, y vuelve a validar el objetivo tras la aprobación, así que nada puede
cambiar por debajo de ti entre el aviso y la acción.

- Se respetan el indicador `confirm` de un paso y la lista de subcadenas `[actions] require_confirm`.
  La lista por defecto es `send`, `submit`, `delete`, `purchase`, `pay` y `confirm order`.
- La confirmación es un canal de interfaz del runner (`host.confirm`), no algo que un complemento declare sobre
  sí mismo. El `needs_confirm` de un complemento es solo una pista no confiable.
- La página **Safety** de la aplicación de ajustes lo llama *Ask before acting* y te deja editar las
  palabras que siempre lo activan.

## Las capacidades peligrosas están desactivadas por defecto

| Op | Por defecto | Notas |
|---|---|---|
| `action.terminal` | **desactivada** | activarla requiere un opt-in explícito y la operación sigue pidiendo confirmación; nunca recibe cadenas derivadas del modelo a menos que lo hayas activado |
| `action.input` (teclado y ratón sin procesar) | **desactivada** | alto riesgo; se prefieren los manejadores nativos e integrados |
| `action.open_url` / `ensure_url` | activada | lista de esquemas permitidos: `http`, `https`, `mailto`. Nada de `file:`, `javascript:` ni nada más |

Activa una operación en la configuración del **runner**:

```toml
[policy]
enabled_ops = ["action.terminal"]   # or "action.input"
# disabled_ops = []
```

La página Safety muestra los mismos interruptores en **Risky abilities**, detrás de un aviso, y mantiene
visible un cartel mientras cualquiera de ellos está activado.

## Confianza en el socket y la IPC

El runner escucha en `$XDG_RUNTIME_DIR/utter/runner.sock`. Los procesos del mismo usuario no deben poder
controlar tu escritorio por defecto:

- el directorio del socket es `0700` y el socket `0600`;
- el runner verifica el par con `SO_PEERCRED` (mismo uid) y una **lista de binarios de cliente
  permitidos**, resuelta a través de `/proc/<pid>/exe`;
- como alternativa, un cliente se autentica con un token mediante `runner.auth`;
- `allow_same_uid = true` es una puerta de escape para desarrollo, no un valor por defecto;
- las peticiones tienen límite de frecuencia.

## Sandbox y permisos de los complementos

Los complementos declaran permisos en su manifiesto (por ejemplo `network`, `microphone`). Con
`[security] enforce = true` en la configuración del runner, los complementos de subproceso se inician bajo
`systemd-run --user --scope` (preferido) o `bwrap`, con: `NoNewPrivileges`, familias de direcciones
restringidas a `AF_UNIX`, un `/tmp` privado, un cgroup de dispositivos con denegación por defecto
(`DevicePolicy=closed` más `DeviceAllow` para los pocos nodos que un proceso necesita — audio solo si el
complemento declara `microphone`), y rutas de sistema/intérprete de solo lectura más las
`read_paths`/`write_paths` declaradas. En versiones de systemd que rechazan estos ajustes en scopes
transitorios, el runner recurre a `bwrap`, que aplica un aislamiento equivalente; si ninguno de los dos
wrappers funciona, los complementos se inician sin endurecimiento y cada permiso queda como **orientativo**.

**Si un permiso no puede aplicarse en una plataforma, se etiqueta como orientativo**, nunca se da por
seguro implícitamente. `assistant doctor` y la página **Plugins** imprimen el estado aplicado-o-orientativo por
complemento, para que veas exactamente qué está realmente contenido.

## Secretos y registro

- Las claves de API remotas, si usas alguna, pasan por el llavero (libsecret) o un archivo `0600`, y se
  ocultan de los registros y de la salida de `doctor`.
- El contenido de pantalla, portapapeles y audio **no** se registra por defecto. El registro de depuración es opcional y
  se avisa de él.
- La visualización en pantalla opcional escribe su archivo de estado en `$XDG_RUNTIME_DIR` (con el modo
  predeterminado; solo el socket del runner es `0700`/`0600`). Su texto es, por diseño, visible en tu pantalla.
- El **texto** de la transcripción es la única excepción: el demonio lo registra en nivel `INFO`, así que puede
  aparecer en el journal de systemd (`journalctl --user`). Baja `[daemon] log_level` a `WARNING`
  para detenerlo. Esto es el texto, no el audio.

## Qué almacena Utter

Utter guarda una pequeña cantidad de estado en disco. Estado persistente (sobrevive al reinicio):

| Ruta | Qué es |
|---|---|
| `~/.config/utter/config.toml` | tus ajustes |
| `~/.local/share/utter/generated.yaml` | el catálogo de aplicaciones generado a partir de tus aplicaciones instaladas |
| `~/.local/share/utter-models/` | pesos de modelos descargados; se conservan al desinstalar |
| `~/.local/state/utter/install.json` | estado de instalación, reversible |

Estado solo en tiempo de ejecución (vive en `$XDG_RUNTIME_DIR`, se borra al cerrar sesión):

| Ruta | Qué es |
|---|---|
| `$XDG_RUNTIME_DIR/utter/osd.json` | estado en vivo de la visualización en pantalla, incluida la transcripción parcial/final actual mientras el panel está abierto; nunca se persiste |
| `$XDG_RUNTIME_DIR/utter/sleep.json` | solo estado dormido/despierto, escrito atómicamente; nunca se persiste |

Utter **no** conserva:

- **audio**: no persisten grabaciones en disco;
- **historial de comandos ni transcripciones como archivos**: no se añade nada a un archivo de historial;
- **contenido de pantalla ni capturas más allá de la sesión en vivo**: las capturas de visión sobrescriben un
  único archivo temporal.

Los únicos datos **específicos de aplicaciones** hoy son los datos de atajos y perfiles por aplicación: el
catálogo generado más tus propias ediciones de perfiles.

:::note[Próximamente: memoria personal]
Una función de memoria personal (el punto de la hoja de ruta mem0) **aún no está implementada**. Cuando llegue
será **local y sin conexión**, **opcional** y se podrá desactivar; desactivarla significará que Utter
no guarda ninguna memoria. Hasta entonces, Utter no tiene función de memoria.
:::

## Cadena de suministro

Instalar un complemento significa ejecutar código no confiable a tu nivel de privilegio. La política prevista es
una firma (minisign sobre el paquete más un índice firmado) y digests fijados, consentimiento explícito
y un sandbox acotado en la instalación. Las descargas de modelos hoy se fijan por SHA-256 sobre HTTPS. Los binarios
de versión llevan suma de comprobación pero **aún no están firmados**; consulta [Publicación de versiones](/reference/releasing/).

## Qué significa esto para ti

- Deja la terminal y la entrada sin procesar desactivadas a menos que las necesites, y desactívalas después.
- Conserva las palabras de confirmación. Añade las tuyas para cualquier cosa que consideres transcendente.
- Trata `allow_same_uid` y `[security] enforce = false` como ajustes de desarrollo.
- Lee la columna de aplicado-u-orientativo antes de confiar un permiso a un complemento de terceros.
- Haz una prueba primero. `UTTER_DRY_RUN` está activado por defecto en el complemento `utter_py`, y
  `python -m utter.daemon --text "..." --dry-run` muestra un plan sin ejecutarlo.
