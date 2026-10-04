---
title: "Primeros pasos"
description: "Tus primeros diez minutos con Utter: las dos teclas de pulsar para hablar, elegir un primer modelo, los dos modos y el modo de suspensión."
banner:
  content: 'Traducción automática sin revisar. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">Cómo contribuir a la traducción</a>.'
---

Esta página da por hecho que Utter está instalado. Si no lo está, empieza por el [resumen de instalación](/install/).

## Requisitos

- **Linux en Wayland** y **macOS**. En Linux, **niri** y **KDE Plasma (KWin)** son compatibles de primera
  clase; otros compositores tienen soporte parcial (escritura, inicio; sin acciones de ventana).
  El dictado es solo para macOS por ahora y se está conectando en Linux.
- **PipeWire** para el audio (Linux).
- **Python 3.12 o posterior**.
- Se recomienda una GPU NVIDIA para los modelos más grandes, pero no es obligatoria. Utter funciona sin
  ningún modelo y con reconocimiento de voz solo por CPU.

## 1. Inicia el runner y abre la aplicación de ajustes

```bash
systemctl --user enable --now utter-runner.service   # start the background runner
assistant doctor                                     # check tools, plugins and permissions
utter-gui                                            # open the settings window
```

Si no se encuentra `utter-gui`, probablemente el prefijo del instalador no esté en tu `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`assistant doctor` te dice qué herramientas de línea de comandos faltan y si tu usuario puede leer
dispositivos de entrada. Las soluciones más habituales están en [Solución de problemas](/help/troubleshooting/).

## 2. Configura tus teclas de pulsar para hablar {#2-set-your-push-to-talk-keys}

Utter tiene **dos** teclas de pulsar para hablar, una por modo. Ambas son nombres de tecla evdev sin más y se
configuran en la página **Voice** de la aplicación de ajustes, o bajo `[ptt]` en
`~/.config/utter/config.toml`:

```toml
[ptt]
dictation_key = "KEY_F13"
assistant_key = "KEY_INSERT"
```

| | Mantén | Qué ocurre con tus palabras | En pantalla |
|---|---|---|---|
| **Asistente** | la *tecla del asistente* (Insert por defecto) | Se convierte en una acción: abrir aplicaciones y sitios, hacer clic, pulsar atajos | Una onda amarilla |
| **Dictado** | la *tecla de dictado* (F13 por defecto) | Se escribe en el campo que tenga el foco (por ahora solo en macOS; en Linux se está conectando) | Una onda azul con «Dictation · typing» |

Cada modo tiene su propio sonido de inicio, así que puedes distinguirlos sin mirar.

Los valores por defecto asumen un remapeo de teclado que convierte una tecla física incómoda en Insert o F13.
La mayoría de la gente querrá teclas que estén realmente en su teclado. Cualquier nombre de evdev sirve
(`KEY_RIGHTCTRL`, `KEY_PAUSE`, `KEY_SCROLLLOCK`, ...). Si usas `keyd`, la
[guía de configuración](/guides/configuration/#keyd-remap) muestra cómo asignar Bloq Mayús y Alt derecha
a los valores por defecto.

El detector de teclas solo necesita que tu usuario esté en el grupo `input`. Nunca captura el teclado,
así que la tecla sigue funcionando en las demás aplicaciones.

## 3. Elige un primer modelo

Abre la página **Models**. La sección **Recommended for your computer** examina tu procesador,
memoria y tarjeta gráfica y sugiere un modelo por nivel:

| Nivel | Qué hace | Para qué se necesita |
|---|---|---|
| **Reconocimiento de voz** | convierte tu voz en texto | todo lo que dices |
| **Modelo de decisión** | elige entre acciones preparadas cuando no coincide ninguna regla | frases más difusas («pull up youtube») |
| **Visión de pantalla** | encuentra un elemento descrito en una captura | «click the search box» cuando falla la accesibilidad |

No se descarga nada sin ti. Empieza por el reconocimiento de voz: sin él, la tecla del asistente
no tiene nada que transcribir. Los modelos de decisión y visión son opcionales y pueden añadirse después.

Pulsa **Get it** junto a una recomendación, o pega una fuente como `hf:org/name` en
**Add a model**. Las descargas se reanudan si se interrumpen y se verifican con su resumen SHA-256.
La [guía de modelos](/guides/models/) enumera lo recomendado para cada clase de GPU y cómo funciona
el almacén de modelos.

## 4. Di algo

Mantén la tecla del asistente, di **«open youtube»** y suelta. Se abre un navegador o se enfoca una pestaña
de YouTube existente. Luego prueba:

- «close this», «fullscreen», «workspace 3», «focus right» (control de ventanas y espacios de trabajo)
- «pause», «next track» (cualquier reproductor multimedia MPRIS)
- «new tab», «find» (los atajos de la propia aplicación enfocada)
- «click the search box» (primero accesibilidad y luego visión, si la instalaste)

Mantén la tecla de dictado y habla para escribir en el campo enfocado (por ahora solo en macOS; en
Linux se está conectando). El dictado nunca ejecuta comandos.

Para ver qué *haría* Utter sin hacerlo, usa el modo de prueba desde un checkout del código:

```bash
python3 -m utter.daemon --text "open youtube" --dry-run
```

## 5. Modo de suspensión {#5-sleep-mode}

Di **«go to sleep»** en modo asistente y Utter libera tu tarjeta gráfica. Los servicios del modelo
de IA se detienen, el modelo de voz se descarga y solo queda vivo un diminuto detector.
**Mantén cualquiera de las teclas de pulsar para hablar para despertarlo**: la voz vuelve en una fracción de segundo y los
modelos más grandes se recargan en segundo plano.

Utter también se duerme **solo** tras 15 minutos sin usarse. Solo cuenta la actividad de Utter
(una tecla de pulsar para hablar, un comando hablado, despertarse), nunca escribir o hacer clic en otras
aplicaciones, así que la tarjeta gráfica se libera mientras trabajas. Despertarlo es la misma pulsación de tecla.

La frase y el temporizador son tuyos, en la página **General** o en el archivo de configuración:

```toml
[sleep]
enabled = true
trigger = ["go to sleep", "take a break"]
services = ["utter-vision", "utter-planner"]   # what gets unloaded
unload_speech = true
on_idle = true                                 # sleep by itself when unused…
idle_minutes = 15                              # …after this long
```

:::note[Un estado de carga]
La visualización en pantalla tiene un estado `loading`, que se muestra mientras los modelos
vuelven tras despertarse o un arranque en frío.
:::

## Siguientes pasos

- [Configuración](/guides/configuration/) para cada sección de configuración, los motores de voz, la
  cabeza de decisión, la visión y el audio.
- [Aplicaciones y acciones](/guides/apps-and-actions/) para editar los atajos de una aplicación o enseñarle a Utter una
  nueva aplicación.
- [Confianza y seguridad](/guides/trust-and-safety/) antes de activar comandos de terminal o entrada sin procesar.
