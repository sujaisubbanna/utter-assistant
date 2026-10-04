---
title: "Introducción"
description: "Qué es Utter, qué hace y las ideas que hay detrás: primero las reglas, un modelo que solo elige y un escritorio que nunca llama a casa."
banner:
  content: 'Traducción automática sin revisar. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">Cómo contribuir a la traducción</a>.'
---

Utter es un **asistente local y consciente del contexto que convierte tu voz en acciones de escritorio para Linux en Wayland y macOS**.
Mantienes pulsada una tecla, dices lo que quieres y Utter lo convierte en algo que hace tu escritorio:
abrir una aplicación o un sitio web, enfocar o cerrar una ventana, cambiar de espacio de trabajo,
reproducir o pausar contenido multimedia, pulsar un atajo propio de la aplicación, hacer clic en un
botón que puede ver o escribir tus palabras en el campo enfocado.

Todo se ejecuta en tu máquina. El reconocimiento de voz, los pequeños modelos de IA y las capturas de pantalla nunca salen de ella.

## Qué hace

| | |
|---|---|
| **Pulsar para hablar** | Mantén la *tecla del asistente* y habla, o la *tecla de dictado* para escribir lo que dices en el campo en el que empezaste (funciona en Linux y macOS). |
| **Acciones de escritorio** | Abre aplicaciones y sitios web, enfoca y cierra ventanas, cambia de espacio de trabajo, controla el reproductor y pulsa atajos de aplicaciones. |
| **Entiende el contexto** | Sabe qué aplicación está enfocada y qué hay en pantalla, primero mediante la información de accesibilidad y solo como último recurso con capturas. |
| **Acciones por aplicación que puedes editar** | 100+ perfiles de aplicaciones (una vez catalogadas tus aplicaciones instaladas) con sus atajos. Cambia cualquier combinación de teclas desde la aplicación de ajustes. |
| **Seguro por defecto** | Las capacidades de riesgo (comandos de terminal, entrada sin procesar) permanecen desactivadas hasta que las actives, y las acciones importantes preguntan primero. |
| **Localizado** | Incluye 10 idiomas de interfaz (en, es, de, fr, it, pt, zh, ja, ko, ru). El idioma hablado es un ajuste aparte, así que puedes usar la interfaz en español y hablar en inglés. |

## Primero las reglas, el modelo solo elige

La mayoría de los asistentes de voz entregan tus palabras a un modelo grande y le dejan decidir qué ejecutar. Utter
hace lo contrario, y esa es la idea central del diseño:

```text
  you speak ──▶ speech-to-text ──▶ router ──▶ safety policy ──▶ desktop actions
                 (local model)      │  rules first                  (keys, windows,
                                    │  then a small local AI          apps, media)
                                    ▼  that only *chooses*
                              app & screen context
```

1. **Las reglas deterministas van primero.** La mayoría de los comandos («open youtube», «close this», «workspace 3»,
   «next track») coinciden con reglas rápidas y predecibles. Los planes de varios pasos, como enfocar una
   ventana y luego cerrarla, los producen directamente las reglas.
2. **Una cabeza de decisión restringida elige, nunca escribe.** Cuando no coincide ninguna regla, Utter construye una
   pequeña lista de acciones candidatas *totalmente resueltas* (como máximo 12, más un «none» obligatorio) y pide
   a un diminuto modelo local que elija una por su letra. Una elección por debajo de un umbral de confianza cuenta
   como abstención. El modelo no puede redactar sus propios argumentos, así que no puede inventar un comando.
3. **Un planificador de forma libre es el último recurso,** y solo se usa cuando fallan tanto las reglas como la cabeza
   de decisión. Puedes desactivarlo por completo.
4. **La percepción solo se usa cuando un paso la necesita.** «Click the search box» prueba primero el
   árbol de accesibilidad. Solo si eso falla, Utter toma una captura y pide a un modelo de visión
   local dónde hacer clic.

Utter elige el nivel más barato que puede satisfacer la intención:

| Nivel | Nombre | Usa | Ejemplo |
|---|---|---|---|
| T0 | Aplicación | aplicación y ventana enfocadas, perfiles de aplicaciones, gestores de URL | «open youtube» con un navegador enfocado abre la URL. Sin modelo, sin captura. |
| T1 | Accesibilidad | el árbol AT-SPI (rol, nombre, acciones) | «press the Play button» encuentra e invoca el nodo. Sin píxeles. |
| T2 | Teclado | atajos por aplicación | «new tab» pulsa `ctrl+t`. |
| T3 | Visión | una captura fundamentada por un modelo de visión local | solo cuando T0 a T2 no pueden resolver el objetivo. |

## El texto de la pantalla puede guiar, nunca ordenar

Todo lo que Utter lee de tu pantalla (títulos de ventanas, nombres de accesibilidad, texto OCR, el
portapapeles, contenido web) se etiqueta como **no confiable**. El contenido no confiable solo puede *seleccionar* entre
opciones que Utter ya ha preparado. Nunca puede convertirse en el argumento de una acción, así que una página web
no puede convencer a Utter de que ejecute un comando o abra una URL arbitraria. El runner rechaza cualquier
petición cuyos argumentos concretos deriven del contenido de la pantalla.

Las capacidades de riesgo están desactivadas por defecto. Ejecutar comandos de terminal y enviar entrada sin procesar de teclado o ratón
debe activarse explícitamente y aun así pide confirmación. La confirmación siempre muestra la
URL, el comando o el objetivo concretos y se vuelve a validar después de que apruebes. Lee más en
[Confianza y seguridad](/guides/trust-and-safety/).

## Totalmente sin conexión

**Nada sale de tu ordenador.** La voz se reconoce localmente, los modelos de IA se ejecutan localmente y
las capturas nunca salen de la máquina. No hay cuenta ni telemetría.

La única vez que Utter se conecta es cuando **tú** descargas un modelo. Si a propósito lo apuntas
a un servidor en otra máquina, la aplicación de ajustes te lo indica en ámbar.

Utter también funciona **sin ningún modelo**. Las reglas, el estado de las ventanas y la accesibilidad se encargan de los
comandos deterministas. Se necesita un modelo de voz para la voz, y los modelos de visión y lenguaje
son extras opcionales que desbloquean las peticiones más difusas.

## Cómo está construido

Por debajo, un diminuto **runner** supervisa **complementos** intercambiables (voz, decisión, percepción,
acciones, salida de voz, interfaz) mediante un único protocolo JSON-RPC versionado. El runner es la frontera
de confianza: posee la política, la confirmación y el plano de datos, y trata cada complemento y su salida
como no confiables.

- El núcleo es Python y solo usa la biblioteca estándar.
- La aplicación de ajustes es Tauri v2 + React. Es un cliente puro: edita el archivo de configuración, llama
  a la CLI `assistant` y controla las unidades de usuario de systemd. No vive en ella ninguna lógica del asistente.
- La integración con el compositor se centra primero en **niri**, y otros compositores de Wayland se gestionan
  mediante herramientas genéricas.

Consulta [Arquitectura](/reference/architecture/) para ver el panorama completo y el
[protocolo de complementos](/plugins/) si quieres ampliarlo.

## Estado

Utter es software joven creado con la ayuda de asistentes de programación de IA y revisado por una persona.
Lee el código antes de confiarle algo importante y, por favor,
[informa de cualquier cosa que parezca incorrecta](https://github.com/sujaisubbanna/utter-assistant/issues).
Linux x86_64 en Wayland y macOS son plataformas compatibles (consulta [macOS](/guides/macos/)).
Windows no es compatible.
