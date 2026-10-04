---
title: "Einführung"
description: "Was Utter ist, was es tut und die Ideen dahinter: Regeln zuerst, ein Modell, das nur auswählt, und ein Desktop, der nie nach Hause telefoniert."
banner:
  content: 'Maschinell übersetzt, nicht geprüft. <a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">So hilfst du bei der Übersetzung</a>.'
---

Utter ist ein **lokaler, kontextbewusster Sprach-zu-Desktop-Aktions-Assistent für Linux unter Wayland und macOS**.
Du hältst eine Taste gedrückt, sagst, was du willst, und Utter macht daraus etwas, das dein Desktop tut:
eine App oder Website öffnen, ein Fenster fokussieren oder schließen, den Arbeitsbereich wechseln, Medien
abspielen oder pausieren, ein App-eigenes Kürzel drücken, auf eine Schaltfläche klicken, die es sieht, oder deine Worte in das fokussierte Feld tippen.

Alles läuft auf deinem Rechner. Spracherkennung, die kleinen KI-Modelle und die Screenshots verlassen ihn nie.

## Was es tut

| | |
|---|---|
| **Push-to-Talk** | Halte die *Assistenten-Taste* gedrückt und sprich, oder halte die *Diktat-Taste* gedrückt, um Gesagtes in ein beliebiges Feld zu tippen (vorerst nur macOS; unter Linux wird es gerade verdrahtet). |
| **Desktop-Aktionen** | Apps und Websites öffnen, Fenster fokussieren und schließen, Arbeitsbereiche wechseln, Medien steuern, App-Kürzel drücken. |
| **Versteht Kontext** | Weiß, welche App fokussiert ist und was auf dem Bildschirm zu sehen ist, zuerst über Barrierefreiheitsinformationen und Screenshots nur als letzten Ausweg. |
| **Pro-App-Aktionen, die du bearbeiten kannst** | 100+ App-Profile, sobald deine installierten Apps katalogisiert sind, mit ihren Kürzeln. Ändere jede Tastenkombination in der Einstellungs-App. |
| **Standardmäßig sicher** | Riskante Fähigkeiten (Terminalbefehle, Roheingabe) bleiben aus, bis du sie einschaltest, und wichtige Aktionen fragen zuerst. |
| **Lokalisiert** | Liefert 10 UI-Sprachen (en, es, de, fr, it, pt, zh, ja, ko, ru). Die gesprochene Sprache ist eine separate Einstellung, du kannst also eine spanische UI und Englisch gesprochen verwenden. |

## Regeln zuerst, das Modell wählt nur

Die meisten Sprachassistenten übergeben deine Worte einem großen Modell und lassen es entscheiden, was ausgeführt wird. Utter
macht das Gegenteil, und das ist die zentrale Designidee:

```text
  you speak ──▶ speech-to-text ──▶ router ──▶ safety policy ──▶ desktop actions
                 (local model)      │  rules first                  (keys, windows,
                                    │  then a small local AI          apps, media)
                                    ▼  that only *chooses*
                              app & screen context
```

1. **Deterministische Regeln kommen zuerst.** Die meisten Befehle („open youtube“, „close this“, „workspace 3“,
   „next track“) passen zu schnellen, vorhersehbaren Regeln. Mehrstufige Pläne wie das Fokussieren eines
   Fensters und anschließende Schließen werden direkt von den Regeln erzeugt.
2. **Ein eingeschränkter Entscheidungskopf wählt aus, er schreibt nie.** Wenn keine Regel passt, baut Utter eine
   kleine Liste *vollständig aufgelöster* Kandidatenaktionen (höchstens 12, plus ein Pflicht-„none“) und bittet
   ein winziges lokales Modell, eine per Buchstabe zu wählen. Eine Wahl unterhalb einer Konfidenzschwelle gilt als
   Enthaltung. Das Modell kann keine eigenen Argumente verfassen, also kann es keinen Befehl erfinden.
3. **Ein freier Planer ist der letzte Ausweg,** und wird nur verwendet, wenn sowohl Regeln als auch der Entscheidungskopf
   versagen. Du kannst ihn vollständig abschalten.
4. **Wahrnehmung wird nur erreicht, wenn ein Schritt sie braucht.** „Click the search box“ versucht zuerst den
   Barrierefreiheitsbaum. Nur wenn das scheitert, macht Utter einen Screenshot und bittet ein lokales Vision-Modell,
   wo geklickt werden soll.

Utter wählt die günstigste Stufe, die die Absicht erfüllen kann:

| Stufe | Name | Verwendet | Beispiel |
|---|---|---|---|
| T0 | App | fokussierte App und Fenster, App-Profile, URL-Handler | „open youtube“ mit fokussiertem Browser öffnet die URL. Kein Modell, kein Screenshot. |
| T1 | Barrierefreiheit | den AT-SPI-Baum (Rolle, Name, Aktionen) | „press the Play button“ findet den Knoten und ruft ihn auf. Keine Pixel. |
| T2 | Tastatur | Pro-App-Kürzel | „new tab“ drückt `ctrl+t`. |
| T3 | Vision | einen Screenshot, verankert durch ein lokales Vision-Modell | nur wenn T0 bis T2 das Ziel nicht auflösen können. |

## Bildschirmtext kann lenken, nie befehlen

Alles, was Utter von deinem Bildschirm liest (Fenstertitel, Barrierefreiheitsnamen, OCR-Text, die
Zwischenablage, Webinhalte), wird als **nicht vertrauenswürdig** markiert. Nicht vertrauenswürdige Inhalte dürfen nur zwischen
Optionen *auswählen*, die Utter bereits vorbereitet hat. Sie können niemals zum Argument einer Aktion werden, eine Webseite
kann Utter also nicht dazu überreden, einen Befehl auszuführen oder eine beliebige URL zu öffnen. Der Runner lehnt jede
Anfrage ab, deren konkrete Argumente aus Bildschirminhalten stammen.

Riskante Fähigkeiten sind standardmäßig aus. Das Ausführen von Terminalbefehlen und das Senden roher Tastatur- oder Maus-
eingabe müssen ausdrücklich aktiviert werden und fragen trotzdem nach Bestätigung. Die Bestätigung zeigt immer die
konkrete URL, den Befehl oder das Ziel und wird nach deiner Zustimmung erneut validiert. Mehr dazu unter
[Vertrauen und Sicherheit](/guides/trust-and-safety/).

## Völlig offline

**Nichts verlässt deinen Computer.** Sprache wird lokal erkannt, die KI-Modelle laufen lokal, und
Screenshots verlassen nie den Rechner. Es gibt kein Konto und keine Telemetrie.

Das einzige Mal, dass Utter online geht, ist, wenn **du** ein Modell herunterlädst. Wenn du es absichtlich auf
einen Server auf einem anderen Rechner richtest, weist dich die Einstellungs-App in Bernstein darauf hin.

Utter funktioniert auch **ganz ohne Modelle**. Regeln, Fensterzustand und Barrierefreiheit erledigen die
deterministischen Befehle. Ein Sprachmodell wird für die Stimme gebraucht, und die Vision- und Sprachmodelle
sind optionale Extras, die die unscharfen Anfragen freischalten.

## Wie es gebaut ist

Unter der Haube überwacht ein winziger **Runner** austauschbare **Plugins** (Sprache, Entscheidung, Wahrnehmung,
Aktionen, Sprachausgabe, UI) über ein einziges versioniertes JSON-RPC-Protokoll. Der Runner ist die Vertrauens-
grenze: Er besitzt Richtlinie, Bestätigung und Datenebene und behandelt jedes Plugin und seine Ausgabe
als nicht vertrauenswürdig.

- Der Kern ist Python und verwendet nur die Standardbibliothek.
- Die Einstellungs-App ist Tauri v2 + React. Sie ist ein reiner Client: Sie bearbeitet die Konfigurationsdatei, ruft
  die `assistant`-CLI auf und steuert systemd-Benutzereinheiten. Keine Assistentenlogik lebt dort.
- Die Compositor-Integration zielt zuerst auf **niri**, andere Wayland-Compositor werden
  über generische Werkzeuge behandelt.

Siehe [Architektur](/reference/architecture/) für das vollständige Bild und das
[Plugin-Protokoll](/plugins/), wenn du es erweitern möchtest.

## Status

Utter ist junge Software, die mit Hilfe von KI-Programmierassistenten erstellt und von einem Menschen geprüft wurde.
Lies den Code, bevor du ihm etwas Wichtiges anvertraust, und bitte
[melde alles, was falsch aussieht](https://github.com/sujaisubbanna/utter-assistant/issues).
Linux x86_64 unter Wayland und macOS sind unterstützte Plattformen (siehe [macOS](/guides/macos/)).
Windows wird nicht unterstützt.
