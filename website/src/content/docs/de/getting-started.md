---
title: "Erste Schritte"
description: "Deine ersten zehn Minuten mit Utter: die beiden Push-to-Talk-Tasten, ein erstes Modell wählen, die beiden Modi und der Schlafmodus."
banner:
  content: 'Maschinell übersetzt, nicht geprüft. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">So hilfst du bei der Übersetzung</a>.'
---

Diese Seite setzt voraus, dass Utter installiert ist. Falls nicht, beginne mit der [Installationsübersicht](/install/).

## Voraussetzungen

- **Linux unter Wayland** und **macOS**. Unter Linux sind **niri** und **KDE Plasma (KWin)** erstklassig;
  andere Compositor erhalten teilweise Unterstützung (Diktat, Tippen, Starten; keine Fensteraktionen).
  Diktat und die Assistenten-Taste funktionieren unter Linux und macOS.
- **PipeWire** für Audio (Linux).
- **Python 3.12 oder neuer**.
- Für die größeren Modelle wird eine NVIDIA-GPU empfohlen, ist aber nicht erforderlich. Utter läuft auch ohne
  Modelle und mit reiner CPU-Spracherkennung.

## 1. Starte den Runner und öffne die Einstellungs-App

```bash
systemctl --user enable --now utter-runner.service   # start the background runner
assistant doctor                                     # check tools, plugins and permissions
utter-gui                                            # open the settings window
```

Wenn `utter-gui` nicht gefunden wird, liegt das Präfix des Installers wahrscheinlich nicht in deinem `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`assistant doctor` sagt dir, welche Kommandozeilenwerkzeuge fehlen und ob dein Benutzer
Eingabegeräte lesen kann. Die häufigsten Lösungen findest du unter [Fehlerbehebung](/help/troubleshooting/).

## 2. Lege deine Push-to-Talk-Tasten fest {#2-set-your-push-to-talk-keys}

Utter hat **zwei** Push-to-Talk-Tasten, eine pro Modus. Beide sind einfache evdev-Tastennamen und werden
auf der Seite **Stimme** der Einstellungs-App oder unter `[ptt]` in
`~/.config/utter/config.toml` festgelegt:

```toml
[ptt]
dictation_key = "KEY_F13"
assistant_key = "KEY_INSERT"
```

| | Halten | Was mit deinen Worten passiert | Auf dem Bildschirm |
|---|---|---|---|
| **Assistent** | die *Assistenten-Taste* (standardmäßig Insert) | Wird zu einer Aktion: Apps und Seiten öffnen, klicken, Kürzel drücken | Eine gelbe Wellenform |
| **Diktat** | die *Diktat-Taste* (standardmäßig F13) | Wird in das Feld getippt, in dem du angefangen hast (funktioniert unter Linux und macOS) | Eine blaue Wellenform mit „Dictation · typing“ |

Jeder Modus hat seinen eigenen Startklang, du kannst sie also unterscheiden, ohne hinzusehen.

Die Standardwerte gehen von einer Tastaturbelegung aus, die eine unbequeme physische Taste in Insert oder F13 verwandelt.
Die meisten werden Tasten wollen, die tatsächlich auf ihrer Tastatur sind. Jeder evdev-Name funktioniert
(`KEY_RIGHTCTRL`, `KEY_PAUSE`, `KEY_SCROLLLOCK`, ...). Wenn du `keyd` verwendest, zeigt die
[Konfigurationsanleitung](/guides/configuration/#keyd-remap), wie du Caps Lock und rechte Alt-Taste
den Standardwerten zuordnest.

Der Tasten-Listener braucht nur, dass dein Benutzer in der Gruppe `input` ist. Er erobert die Tastatur nie,
also funktioniert die Taste auch für andere Apps weiter.

## 3. Wähle ein erstes Modell

Öffne die Seite **Modelle**. Der Abschnitt **Recommended for your computer** schaut auf deinen Prozessor,
Arbeitsspeicher und deine Grafikkarte und schlägt ein Modell pro Stufe vor:

| Stufe | Was es tut | Benötigt für |
|---|---|---|
| **Spracherkennung** | wandelt deine Stimme in Text um | alles, was du sagst |
| **Entscheidungsmodell** | wählt unter vorbereiteten Aktionen, wenn keine Regel passt | unschärfere Formulierungen („pull up youtube“) |
| **Bildschirm-Vision** | findet ein beschriebenes Element in einem Screenshot | „click the search box“, wenn Barrierefreiheit versagt |

Nichts wird ohne dich heruntergeladen. Beginne mit der Spracherkennung: Ohne sie hat die Assistenten-Taste
nichts zu transkribieren. Das Entscheidungs- und das Vision-Modell sind optional und können später hinzugefügt werden.

Drücke **Get it** neben einem Vorschlag, oder füge eine Quelle wie `hf:org/name` in
**Add a model** ein. Downloads werden bei Unterbrechung fortgesetzt und gegen ihren SHA-256-Digest geprüft.
Die [Modelle-Anleitung](/guides/models/) listet, was für jede GPU-Klasse empfohlen wird und wie der
Modellspeicher funktioniert.

## 4. Sag etwas

Halte die Assistenten-Taste, sag **„open youtube“**, lass los. Ein Browser öffnet sich oder ein vorhandener YouTube-
Tab wird fokussiert. Probiere dann:

- „close this“, „fullscreen“, „workspace 3“, „focus right“ (Fenster- und Arbeitsbereichssteuerung)
- „pause“, „next track“ (jeder MPRIS-Mediaplayer)
- „new tab“, „find“ (die eigenen Kürzel der fokussierten App)
- „click the search box“ (zuerst Barrierefreiheit, dann Vision, falls installiert)

Halte die Diktat-Taste und sprich, um in das Feld zu tippen, in dem du angefangen hast (Linux und
macOS). Diktat führt nie Befehle aus.

Um zu sehen, was Utter *tun würde*, ohne es zu tun, verwende den Testlauf aus einem Quellcode-Checkout:

```bash
python3 -m utter.daemon --text "open youtube" --dry-run
```

## 5. Schlafmodus {#5-sleep-mode}

Sag **„go to sleep“** im Assistentenmodus und Utter gibt deine Grafikkarte frei. Die KI-Modell-
dienste stoppen, das Sprachmodell wird entladen, und nur ein winziger Listener bleibt aktiv.
**Halte eine der beiden Push-to-Talk-Tasten, um ihn zu wecken**: Sprache ist im Bruchteil einer Sekunde zurück, und die
größeren Modelle laden im Hintergrund nach.

Utter schläft auch **von selbst** ein, nach 15 Minuten ohne Benutzung. Nur Utter-Aktivität
zählt (eine Push-to-Talk-Taste, ein gesprochener Befehl, Aufwachen), niemals Tippen oder Klicken in anderen
Apps, die Grafikkarte wird also frei, während du arbeitest. Das Aufwecken ist derselbe Tastendruck.

Die Formulierung und der Timer sind deine Wahl, auf der Seite **Allgemein** oder in der Konfigurationsdatei:

```toml
[sleep]
enabled = true
trigger = ["go to sleep", "take a break"]
services = ["utter-vision", "utter-planner"]   # what gets unloaded
unload_speech = true
on_idle = true                                 # sleep by itself when unused…
idle_minutes = 15                              # …after this long
```

:::note[Ein Ladezustand]
Das Bildschirm-OSD hat einen `loading`-Zustand, der angezeigt wird, während die Modelle nach einem
Aufwachen oder Kaltstart zurückkehren.
:::

## Nächste Schritte

- [Konfiguration](/guides/configuration/) für jeden Konfigurationsabschnitt, Sprach-Backends, den
  Entscheidungskopf, Vision und Audio.
- [Apps und Aktionen](/guides/apps-and-actions/), um die Kürzel einer App zu bearbeiten oder Utter eine neue
  Anwendung beizubringen.
- [Vertrauen und Sicherheit](/guides/trust-and-safety/), bevor du Terminalbefehle oder Roheingabe aktivierst.
