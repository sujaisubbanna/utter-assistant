import { useEffect, useState } from "react";

import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigSwitch, ConfigText, SelectSetting } from "../components/Setting";
import { Badge } from "../components/ui/Badge";
import { Button, LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Row, Tile } from "../components/ui/Row";
import { useToast } from "../components/ui/Toast";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { linkFor } from "../lib/links";
import { usePlatform } from "../lib/platform";
import { optionLabel, TTS_ENGINES } from "../lib/services";
import { TtsMacPage } from "./TtsMac";

const ENGINE_BINARY: Record<string, string> = {
  "espeak-ng": "espeak-ng",
  espeak: "espeak",
  "spd-say": "spd-say",
  piper: "piper",
};

export function TtsPage() {
  const { isMac } = usePlatform();
  if (isMac) return <TtsMacPage />;
  return <TtsLinuxPage />;
}

function TtsLinuxPage() {
  const t = useT();
  const { get, set } = useConfig();
  const toast = useToast();
  const [available, setAvailable] = useState<Record<string, boolean>>({});
  const [phrase, setPhrase] = useState("");
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    api
      .whichMany(TTS_ENGINES.map((engine) => ENGINE_BINARY[engine.value]))
      .then(setAvailable)
      .catch(() => setAvailable({}));
  }, []);

  const engine = String(get("tts", "engine", "espeak-ng"));
  const language = String(get("tts", "language", "auto"));
  const voice = String(get("tts", "voice", ""));
  const engineDef = TTS_ENGINES.find((item) => item.value === engine);
  const engineName = engineDef ? optionLabel(engineDef, t) : engine;
  const missing = available[ENGINE_BINARY[engine]] === false;
  const engineLink = engineDef?.link ? linkFor(engineDef.link) : undefined;
  // An empty voice means "derive from the language / engine default"; for the
  // test command, espeak engines can take the configured language directly.
  const testVoice = voice.trim()
    ? voice.trim()
    : language.trim() !== "auto" && engine.startsWith("espeak")
      ? language.trim().toLowerCase()
      : "";

  const test = async () => {
    setTesting(true);
    try {
      const result = await api.ttsTest(engine, testVoice, phrase.trim() || t("tts.test.defaultPhrase"));
      toast(
        result.ok
          ? t("tts.test.spoken")
          : t("tts.test.failed", { name: engineName, detail: (result.stderr || result.stdout).trim().slice(0, 120) }),
        result.ok ? "ok" : "error",
      );
    } catch (error) {
      toast(t("tts.test.couldNotRun", { name: engineName, detail: String(error) }), "error");
    } finally {
      setTesting(false);
    }
  };

  const options = TTS_ENGINES.map((item) => {
    const present = available[ENGINE_BINARY[item.value]];
    const label = optionLabel(item, t);
    return { value: item.value, label: present === false ? `${label} — ${t("common.notInstalled")}` : label };
  });

  return (
    <>
      <PageHeader title={t("tts.title")} description={t("tts.description")} />
      <PageBody config>
        <Section title={t("tts.output.title")} description={t("tts.output.description")}>
          <ConfigSwitch
            section="tts"
            k="enabled"
            title={t("tts.output.enable")}
            description={t("tts.output.enableHint")}
          />
          <SelectSetting
            title={t("tts.output.engine")}
            description={missing ? t("tts.output.missing", { name: engineName }) : t("tts.output.engineHint")}
            value={engine}
            options={options}
            onChange={(next) => void set("tts", "engine", next)}
            extra={
              missing && engineLink ? (
                <LinkButton href={engineLink}>{t("tts.output.getIt", { name: engineName })}</LinkButton>
              ) : undefined
            }
          />
          <ConfigText
            section="tts"
            k="language"
            title={t("tts.output.language")}
            description={t("tts.output.languageHint")}
            fallback="auto"
            placeholder="auto"
            monospace
            width="w-24"
          />
          <ConfigText
            section="tts"
            k="voice"
            title={t("tts.output.voice")}
            description={t("tts.output.voiceHint")}
            fallback=""
            placeholder="auto"
            monospace
            width="w-40"
          />
        </Section>

        <Section title={t("tts.test.title")} description={t("tts.test.description")}>
          <Row leading={<Tile icon="volume" tone="accent" />} title={t("tts.test.phrase")}>
            {missing && <Badge tone="warn">{t("common.notInstalled")}</Badge>}
            <Input
              value={phrase}
              placeholder={t("tts.test.defaultPhrase")}
              onChange={(event) => setPhrase(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void test();
              }}
              className="w-64"
              aria-label={t("tts.test.phrase")}
            />
            <Button variant="primary" icon="play" loading={testing} disabled={missing} onClick={() => void test()}>
              {t("tts.test.speak")}
            </Button>
          </Row>
        </Section>
      </PageBody>
    </>
  );
}
