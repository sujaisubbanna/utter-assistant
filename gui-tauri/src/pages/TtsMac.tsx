import { useState } from "react";

import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigNumber, ConfigText, SelectSetting } from "../components/Setting";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Row, Tile } from "../components/ui/Row";
import { useToast } from "../components/ui/Toast";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { humanizeError } from "../lib/errors";
import { MAC_TTS_BACKENDS, optionLabel } from "../lib/services";

/** Spoken replies on macOS: the system `say` voices or AVSpeechSynthesizer. */
export function TtsMacPage() {
  const t = useT();
  const { get, set } = useConfig();
  const toast = useToast();
  const [phrase, setPhrase] = useState("");
  const [testing, setTesting] = useState(false);

  const backend = String(get("macos", "tts_backend", "say"));
  const voice = String(get("macos", "tts_voice", ""));
  const disabled = backend === "none";

  const test = async () => {
    setTesting(true);
    try {
      // The backend maps "say"/"avspeech" to the system `say` CLI; an empty
      // voice means the system default.
      const result = await api.ttsTest("say", voice || "en", phrase.trim() || t("tts.test.defaultPhrase"));
      toast(
        result.ok ? t("tts.test.spoken") : t("tts.test.failed", { name: "say", detail: humanizeError((result.stderr || result.stdout).trim().slice(0, 120), t) }),
        result.ok ? "ok" : "error",
      );
    } catch (error) {
      toast(t("tts.test.couldNotRun", { name: "say", detail: humanizeError(error, t) }), "error");
    } finally {
      setTesting(false);
    }
  };

  return (
    <>
      <PageHeader title={t("tts.title")} description={t("tts.mac.description")} />
      <PageBody config>
        <Section title={t("tts.output.title")} description={t("tts.output.description")}>
          <SelectSetting
            title={t("tts.output.engine")}
            description={t("tts.mac.engineHint")}
            value={backend}
            options={MAC_TTS_BACKENDS.map((item) => ({ value: item.value, label: optionLabel(item, t) }))}
            onChange={(next) => void set("macos", "tts_backend", next)}
          />
          <ConfigText
            section="macos"
            k="tts_voice"
            title={t("tts.output.voice")}
            description={t("tts.mac.voiceHint")}
            placeholder={t("common.default")}
            monospace
            width="w-40"
          />
          <ConfigNumber
            section="macos"
            k="tts_rate"
            title={t("tts.mac.rate")}
            description={t("tts.mac.rateHint")}
            fallback={0}
            min={0}
            max={400}
            step={10}
          />
        </Section>

        <Section title={t("tts.test.title")} description={t("tts.test.description")}>
          <Row leading={<Tile icon="volume" tone="accent" />} title={t("tts.test.phrase")}>
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
            <Button variant="primary" icon="play" loading={testing} disabled={disabled} onClick={() => void test()}>
              {t("tts.test.speak")}
            </Button>
          </Row>
        </Section>
      </PageBody>
    </>
  );
}
