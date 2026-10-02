---
title: "Instalación"
description: "Las formas de instalar Utter en Linux y macOS: clonar e instalar, el instalador remoto de una línea o compilar desde el código fuente."
banner:
  content: 'Traducción automática sin revisar. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">Cómo contribuir a la traducción</a>.'
---

Utter funciona en **Linux en Wayland** y **macOS**. En Linux, **niri** y **KDE Plasma (KWin)** son
compatibles de primera clase y otros compositores tienen soporte parcial (dictado, escritura, inicio;
sin acciones de ventana); Linux necesita **PipeWire**. Ambas plataformas necesitan **Python 3.12+**.
Consulta [macOS](/guides/macos/) para la configuración específica de macOS.
Se recomienda una GPU NVIDIA para los modelos más grandes, pero no es obligatoria.
Compilar la aplicación de ajustes requiere Node + pnpm y una cadena de herramientas de Rust. Hoy solo se
publican binarios de versión x86_64 para Linux; macOS distribuye paquetes `.dmg` para Apple Silicon e Intel.

El instalador es un **asistente interactivo**. Recorre cada componente (el runner y la CLI `assistant`,
tu idioma hablado, la aplicación de ajustes, los servicios en segundo plano, los modelos de voz y el
widget opcional de Noctalia) y pregunta si lo quieres. En una terminal, Intro acepta el
valor recomendado por defecto. `--yes` los acepta todos sin interacción. Cada descarga se verifica con
el `sha256sums.txt` de la versión.

**El inglés viene incluido**: el paso de idioma usa el inglés por defecto y no descarga nada, así que
la instalación por defecto no necesita obtener ningún modelo. Los demás idiomas son opcionales: el paso ofrece el
modelo de voz multilingüe y la voz correspondientes (con tamaños) y solo descarga lo que aceptes.

Elige la ruta que más te convenga; el instalador remoto funciona tanto en Linux (Wayland) como en
macOS. Consulta [macOS](/guides/macos/) para la instalación manual con `.dmg` o Homebrew.

## 1. Clonar e instalar

Conserva el repositorio e instala desde tu propio checkout:

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant

./install.sh --dry-run   # walk the wizard, print the plan, change nothing
./install.sh             # install the components you choose
```

¿Quieres la instalación más pequeña posible, con los paquetes de la distro y el servicio en segundo plano y nada más?
Usa el instalador de desarrollo:

```bash
install/install.sh --dry-run
install/install.sh --yes
```

Deshaz cualquiera de las dos con `./install.sh --uninstall`. Los detalles, incluido lo que hace paso a paso el instalador
de desarrollo, están en [Clonar y compilar desde el código fuente](/install/from-source/).

## 2. Instalación remota

Sin necesidad de clonar:

```bash
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
```

:::note[Un pipe sin más no cambia nada]
La entrada canalizada no es una terminal, así que el asistente no puede preguntar. Un `curl | bash` sin más **imprime el
plan y sale sin cambiar nada**. Pasa `--yes` para aceptar los valores recomendados, o
cualquier otro indicador:
:::

```bash
# recommended defaults, no prompts
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes

# native package (.deb/.rpm) through your package manager instead of the AppImage (needs sudo)
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --package --yes

# only these components
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --only core,gui --yes
```

Otros indicadores: `--skip <csv>`, `--with-noctalia`, `--dry-run`, `--uninstall`. La matriz completa de indicadores y
variables de entorno, los diez pasos del asistente y dónde acaba todo están en
[Instalar desde la web](/install/remote/).

## 3. Compilar desde el código fuente

El núcleo del asistente es Python solo con la biblioteca estándar; la aplicación de ajustes es Tauri v2 + React + Tailwind CSS v4.

```bash
# the assistant core, straight from the checkout
python3 -m utter.daemon --text "open youtube" --dry-run
scripts/verify.sh            # unit + e2e + conformance

# the settings app
cd gui-tauri
pnpm install
pnpm tauri build             # release binary (and a .deb) in src-tauri/target/release
pnpm tauri dev               # ...or run it with hot reload
```

En Wayland con una configuración de doble NVIDIA, inicia la aplicación compilada con el renderizador DMABUF desactivado.
El lanzador `utter-gui` lo hace por ti:

```bash
WEBKIT_DISABLE_DMABUF_RENDERER=1 ./gui-tauri/src-tauri/target/release/utter
```

Consulta [Clonar y compilar desde el código fuente](/install/from-source/) para los servicios, la CLI `assistant` y
el almacén de modelos.

## Requisitos de GPU y latencia

Los scripts de servicio incluidos asumen **una GPU NVIDIA compartida por ambos servidores vLLM**. Huella por
componente:

| Componente | Modelo | Precisión | Ajuste de memoria de GPU | En disco |
|---|---|---|---|---|
| Reconocimiento de voz (en proceso) | `distil-small.en` | faster-whisper, float16 | ~0.5 GB | — |
| Cabeza de decisión / planificador | `Qwen3-4B-Instruct-2507-AWQ-4bit` | W4A16 (4-bit AWQ) | `--gpu-memory-utilization 0.30` | 3.3 GB |
| Visión de pantalla | `UI-TARS-2B-SFT` | bf16 | `--gpu-memory-utilization 0.55` | 9.2 GB |

`0.30 + 0.55 = 0.85`, así que el par por defecto cabe en una GPU de ~24 GB.

| Nivel | Qué se ejecuta | Estado |
|---|---|---|
| **24 GB** | Pila completa; planificador ~7.2 GB (0.30), visión ~13 GB (0.55); juntos ~0.85 de la tarjeta | Cabe en los valores por defecto: las cifras de latencia siguientes se midieron con ambos modelos en una tarjeta de 24 GB |
| **16 GB** | Los mismos modelos con `UTTER_VISION_GPU_MEM_UTIL` y `UTTER_PLANNER_GPU_MEM_UTIL` más bajos (suma por debajo de ~0.9) | **Compatible** |
| **8 GB** | Visión 2B + planificador 4B AWQ con menor utilización (`assistant recommend` estima 4B AWQ ≈ 3 GB, UI-TARS-2B ≈ 4 GB) | **Compatible** |
| **Sin GPU / solo CPU** | Visión desactivada (solo accesibilidad), STT más pequeño | **Compatible** |

La fila de 24 GB es el objetivo de los valores por defecto; las otras filas usan ajustes de menor utilización.
Usa `assistant recommend` para ver qué cabe en tu máquina.

La latencia se midió en una **NVIDIA RTX 3090 Ti (24 GB)** con los modelos anteriores, el **2026-10-02**
(30 llamadas en caliente y 1 llamada en frío por ruta). Variará según la máquina.

| Ruta | En frío (primera llamada) | Caliente p50 | Caliente p95 |
|---|---|---|---|
| Reglas (capa 1, sin modelo) | 9.2 ms | <1 ms | <1 ms |
| Cabeza de decisión (capa 2, LLM local) | 108.8 ms | 9.2 ms | 11.6 ms |
| Visión (fundamentación de capturas UI-TARS) | 676.5 ms | 91.0 ms | 140.6 ms |
| Extremo a extremo `utter assistant --dry-run` | 114 ms | 113 ms | 114 ms |
| Suspensión → despertar (recarga del planificador hasta listo) | ~21 s | — | — |

- **«En frío»** es la primera llamada cuando los servidores están activos pero inactivos (kernels/cachés CUDA en frío), no
  la carga del modelo.
- El tiempo extremo a extremo está dominado por el arranque del intérprete de Python (~113 ms), no por la cabeza de decisión
  (unos 9 ms en caliente).
- Las cifras de visión incluyen una imagen sintética de 1344×756.

Consulta [Modelos](/guides/models/) para las reglas de recomendación y el almacén de modelos.

## Después de instalar

Abre la **aplicación de ajustes de Utter**, configura tus teclas de pulsar para hablar en la página **Voz** y elige un
modelo recomendado en la página **Modelos**. Luego sigue [Primeros pasos](/getting-started/).

```bash
systemctl --user enable --now utter-runner.service   # start the runner
assistant doctor --json                              # verify deps + plugins
utter-gui                                            # open the settings window
```
