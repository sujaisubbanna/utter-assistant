---
title: "Preguntas frecuentes"
description: "Respuestas cortas a las preguntas que la gente hace primero sobre Utter."
banner:
  content: 'Traducción automática sin revisar. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">Cómo contribuir a la traducción</a>.'
---

### ¿Sale algo de mi ordenador?

No. El reconocimiento de voz, los modelos de lenguaje y visión y las capturas de pantalla se ejecutan y se quedan
localmente. No hay cuenta ni telemetría. El único uso de la red es descargar un modelo cuando
**tú** lo pides, y la única excepción deliberada es apuntar un endpoint de modelo a un servidor en
otra máquina, algo que la aplicación de ajustes señala en ámbar.

### ¿Necesito una GPU?

No. Utter funciona sin ningún modelo para los comandos que coinciden con reglas, y el reconocimiento de voz se ejecuta en
CPU con whisper.cpp. Una GPU hace que la voz sea más rápida y es necesaria para los modelos opcionales de cabeza de decisión y
visión. La configuración cómoda para los tres es una tarjeta NVIDIA de 16 GB o más; consulta
[Modelos](/guides/models/) para la recomendación por clase de GPU.

### ¿Por qué se durmió Utter solo?

Por defecto, Utter se duerme tras 15 minutos sin usarse, así la tarjeta gráfica queda libre mientras
trabajas en otra cosa. Solo la actividad de *Utter* lo mantiene despierto: una tecla de pulsar para hablar, un comando
hablado o despertarse. Escribir o hacer clic en otras aplicaciones no cuenta, y nunca se adormece
mientras escucha o ejecuta un comando. Mantén cualquiera de las teclas de pulsar para hablar para despertarlo; la voz
vuelve en una fracción de segundo y los modelos más grandes se recargan en segundo plano. Desactívalo
o cambia el tiempo en **Sleep when idle** en la página General, o ajusta `[sleep] on_idle` e
`idle_minutes` en el archivo de configuración.

### ¿Funciona en X11, GNOME, KDE, Hyprland, sway?

Utter apunta a **Wayland**. **niri** y **KDE Plasma (KWin)** son de primera clase: una pequeña capa de compositor
detecta cuál se está ejecutando y usa su interfaz nativa para las acciones de ventana y espacio de trabajo
(`niri msg` en niri, las interfaces D-Bus de KWin en Plasma). Otros compositores de Wayland tienen soporte
parcial: las herramientas genéricas que usa (`wtype`, `ydotool`, `grim`, `wl-clipboard`, PipeWire, MPRIS,
AT-SPI) funcionan en varios compositores, así que la escritura y el inicio funcionan, pero las acciones
específicas del compositor (enfocar, mover, espacios de trabajo) no están implementadas para ellos. X11 no es compatible.

### ¿Windows o macOS?

**macOS es compatible**: voz nativa con `Speech.framework` + whisper.cpp, pulsar para hablar e
inyección con Quartz, y un `.dmg` para Apple Silicon e Intel. El `.dmg` no está firmado a menos que
se configuren credenciales de Apple Developer; en el primer inicio, haz clic derecho → *Abrir* o ejecuta
`xattr -cr /Applications/utter.app`. Consulta [macOS](/guides/macos/).
**Windows no es compatible** y no se ha empezado.

### ¿Cuál es la diferencia entre la tecla del asistente y la tecla de dictado?

Mantén la **tecla del asistente** y tus palabras se convierten en una acción. Mantén la **tecla de dictado** y tus
palabras se escriben en el campo enfocado, nada más (por ahora solo en macOS; en Linux se está conectando). Cada
una tiene su propio sonido y color de onda.
Consulta [Primeros pasos](/getting-started/#2-set-your-push-to-talk-keys).

### ¿Por qué Insert y F13 como valores por defecto?

Porque la configuración de referencia remapea Alt derecha a Insert y Bloq Mayús a F13 con keyd, lo que
da dos teclas grandes y cómodas que nada más usa. Cámbialas en la página Voz por cualquier
tecla que quieras.

### ¿Puede la IA ejecutar comandos arbitrarios?

No. Las reglas van primero. Cuando ninguna regla coincide, un pequeño modelo local **elige** entre acciones
totalmente resueltas que Utter ya ha preparado; no puede escribir las suyas. Ejecutar comandos de terminal
está desactivado por defecto, y cualquier cosa derivada del contenido de la pantalla nunca puede convertirse en un argumento. Consulta
[Confianza y seguridad](/guides/trust-and-safety/).

### ¿`curl | bash` instalará cosas sin preguntar?

No por sí solo. La entrada canalizada no es una terminal, así que el asistente no puede preguntar: un pipe sin más imprime
el plan y sale sin cambiar nada. Añade `--yes` para aceptar los valores recomendados.
También puedes leer el script primero; es `install.sh` en la raíz del repositorio.

### ¿El instalador descarga modelos?

Nunca por sí solo. El paso de modelos pregunta por nivel y solo descarga cuando lo aceptas y proporcionas una
fuente. La aplicación de ajustes tampoco descarga nada hasta que pulsas el botón.

### ¿Cómo desinstalo?

`./install.sh --uninstall` desde un checkout, o el comando remoto de una línea con `--uninstall`. Tu
configuración y tus modelos se conservan a menos que los elimines tú mismo. Consulta
[Instalar desde la web](/install/remote/#uninstall).

### ¿Puedo usar mi propio servidor de modelo de lenguaje?

Sí. Cualquier cosa compatible con OpenAI funciona: vLLM, Ollama, llama.cpp. Configura `[router] llm_base_url` y
`llm_model`, y `[vision] base_url` y `model`, o usa las páginas de LLM y Percepción.

### ¿Cómo le enseño una nueva aplicación?

Crea un perfil YAML en `~/.config/utter/profiles/` o edita la aplicación en la página **App actions**,
y luego regenera el catálogo. Consulta [Aplicaciones y acciones](/guides/apps-and-actions/).

### ¿Qué idiomas habla?

La aplicación de ajustes y el instalador incluyen 10 idiomas de interfaz: inglés, español, alemán, francés,
italiano, portugués, chino, japonés, coreano y ruso. El idioma hablado es un ajuste aparte
(por defecto, el de tu sistema), así que puedes usar la interfaz en español y hablar en inglés.
El reconocimiento de voz depende del modelo: por defecto es un modelo whisper solo para inglés (`.en`),
y puedes optar por un modelo multilingüe (`small`, `large-v3-turbo`, …) desde la aplicación de ajustes o el
instalador. Utter nunca descarga un modelo por su cuenta.

### ¿Está terminado Utter?

No. Es software joven creado con asistentes de programación de IA y revisado por una persona. Lee el código
antes de confiarle algo importante e informa de cualquier cosa que parezca incorrecta.
