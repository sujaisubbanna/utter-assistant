import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "../components/icons";
import { ModelRequiredBanner } from "../components/ModelRequired";
import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigText, SelectSetting } from "../components/Setting";
import { Badge } from "../components/ui/Badge";
import { Button, LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Modal } from "../components/ui/Modal";
import { Row, Tile } from "../components/ui/Row";
import { Skeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { useTauriEvent } from "../lib/events";
import { displayName, domCodeToEvdev, isModifier } from "../lib/keys";
import { linkFor } from "../lib/links";
import { usePlatform } from "../lib/platform";
import { optionLabel, STT_BACKENDS, STT_DEVICES } from "../lib/services";
import { VoiceMacPage } from "./VoiceMac";

function KeyCaptureModal({
  open,
  title,
  current,
  onClose,
  onCaptured,
}: {
  open: boolean;
  title: string;
  current: string;
  onClose: () => void;
  onCaptured: (evdev: string) => void;
}) {
  const t = useT();
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      if (event.key === "Escape") {
        onClose();
        return;
      }
      const name = domCodeToEvdev(event.code);
      if (!name) {
        setPreview(t("voice.keys.unmapped", { code: event.code }));
        return;
      }
      onCaptured(name);
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onCaptured, onClose, t]);

  return (
    <Modal open={open} onClose={onClose} title={t("voice.keys.modalTitle", { name: title.toLowerCase() })} size="sm">
      <div className="flex flex-col items-center gap-4 pb-1 pt-3 text-center">
        <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-accent-text">
          <span className="absolute inset-0 animate-dot-pulse rounded-2xl text-primary" aria-hidden="true" />
          <Icon name="keyboard" size={26} />
        </span>
        <div>
          <div className="text-[15px] font-semibold text-foreground">{t("voice.keys.press")}</div>
          <p className="mt-1 text-xs text-muted-foreground">{t("voice.keys.escape")}</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {t("voice.keys.current")}
          <span className="kbd">{current ? displayName(current) : t("voice.keys.notSet")}</span>
        </div>
        {preview && <p className="text-xs text-[color:var(--warning)]">{preview}</p>}
      </div>
    </Modal>
  );
}

function KeyRow({ title, description, field }: { title: string; description: string; field: string }) {
  const t = useT();
  const { get, set } = useConfig();
  const [open, setOpen] = useState(false);
  const current = String(get("ptt", field, ""));
  return (
    <Row title={title} description={description} leading={<Tile icon="keyboard" />}>
      {current && isModifier(current) && <Badge tone="muted">{t("voice.keys.modifier")}</Badge>}
      <span className="kbd">{current ? displayName(current) : t("voice.keys.notSet")}</span>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("voice.keys.change")}
      </Button>
      <KeyCaptureModal
        open={open}
        title={title}
        current={current}
        onClose={() => setOpen(false)}
        onCaptured={(name) => void set("ptt", field, name)}
      />
    </Row>
  );
}

const BARS = 24;

function LevelMeter({ active }: { active: boolean }) {
  const [level, setLevel] = useState(0);
  const peak = useRef(0);

  useTauriEvent<{ level: number }>(
    "mic://level",
    (payload) => {
      peak.current = Math.max(payload.level, peak.current * 0.7);
    },
    active,
  );

  useEffect(() => {
    if (!active) {
      peak.current = 0;
      setLevel(0);
      return;
    }
    const id = window.setInterval(() => {
      peak.current *= 0.86;
      setLevel(peak.current);
    }, 70);
    return () => window.clearInterval(id);
  }, [active]);

  const lit = Math.round(Math.min(1, level * 1.3) * BARS);
  return (
    <div className="flex h-5 items-center gap-[3px]" aria-hidden="true">
      {Array.from({ length: BARS }).map((_, index) => (
        <span
          key={index}
          className="h-full w-[3px] rounded-full transition-colors duration-75"
          style={{
            background:
              index < lit
                ? index > BARS * 0.8
                  ? "var(--warning)"
                  : "var(--primary)"
                : "var(--line-strong)",
          }}
        />
      ))}
    </div>
  );
}

export function VoicePage() {
  const { isMac } = usePlatform();
  if (isMac) return <VoiceMacPage />;
  return <VoiceLinuxPage />;
}

/** Whisper ".en" checkpoints are English-only (mirrors `stt.py`). */
const ENGLISH_ONLY_MODEL = /(?:^|[.-])en(?:[.-]|$)/i;

function isEnglishOnlyModel(model: string): boolean {
  const name = (model.split("/").pop() ?? model).trim().toLowerCase();
  const stem = name.endsWith(".bin") ? name.slice(0, -4) : name;
  return ENGLISH_ONLY_MODEL.test(stem);
}

/** The webview follows the system locale the daemon also reads. */
function systemLanguageCode(): string {
  const raw = (navigator.language || "").trim().toLowerCase();
  return raw === "c" || raw === "posix" ? "" : raw;
}

const MULTILINGUAL_CHOICES = [
  { model: "small", size: "~480 MB" },
  { model: "large-v3-turbo", size: "~1.6 GB" },
];

/**
 * Explicit, user-driven model switch when the spoken language is not English
 * but the configured Whisper checkpoint is English-only. Nothing is downloaded
 * here: the speech engine fetches the chosen model on first use.
 */
function SttLanguageMismatch() {
  const t = useT();
  const { get, setMany } = useConfig();
  const language = String(get("stt", "language", "auto")).trim().toLowerCase();
  const model = String(get("stt", "model", "ggml-small.en.bin"));
  const effective = language === "auto" || language === "" ? systemLanguageCode() : language;
  if (!effective || effective.startsWith("en") || !isEnglishOnlyModel(model)) return null;
  return (
    <div className="flex items-start gap-3 rounded-lg bg-[color-mix(in_oklab,var(--warning)_10%,var(--card))] px-4 py-3.5 shadow-[0_0_0_1px_color-mix(in_oklab,var(--warning)_30%,transparent)]">
      <Icon name="info" size={16} className="mt-0.5 shrink-0 text-[color:var(--warning)]" />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-foreground">{t("voice.stt.mismatch.title")}</div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {t("voice.stt.mismatch.body", { language: effective, model })}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {MULTILINGUAL_CHOICES.map((choice) => (
            <Button
              key={choice.model}
              size="sm"
              variant="secondary"
              icon="download"
              onClick={() => void setMany("stt", { model: choice.model })}
            >
              {t("voice.stt.mismatch.use", { model: choice.model, size: choice.size })}
            </Button>
          ))}
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">{t("voice.stt.mismatch.downloadHint")}</p>
      </div>
    </div>
  );
}

function VoiceLinuxPage() {
  const t = useT();
  const { get, set, loading } = useConfig();
  const toast = useToast();
  const [sources, setSources] = useState<{ name: string; description: string }[] | null>(null);
  const [monitoring, setMonitoring] = useState(false);

  const loadSources = useCallback(async () => {
    try {
      setSources(await api.pactlSources());
    } catch {
      setSources([]);
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    if (!monitoring) return;
    void api.startMic().catch(() => {
      toast(t("voice.mic.startError"), "error");
      setMonitoring(false);
    });
    return () => {
      void api.stopMic();
    };
  }, [monitoring, toast, t]);

  const device = String(get("audio", "device", ""));
  const backend = String(get("stt", "backend", "faster_whisper"));
  const backendDef = STT_BACKENDS.find((item) => item.value === backend);
  const backendLink = backendDef?.link ? linkFor(backendDef.link) : undefined;

  return (
    <>
      <PageHeader title={t("voice.title")} description={t("voice.description")} />
      <PageBody config>
        <ModelRequiredBanner kind="stt" />

        <Section title={t("voice.keys.title")} description={t("voice.keys.description")}>
          <KeyRow title={t("voice.keys.assistant")} description={t("voice.keys.assistantHint")} field="assistant_key" />
          <KeyRow title={t("voice.keys.dictation")} description={t("voice.keys.dictationHint")} field="dictation_key" />
        </Section>

        <Section title={t("voice.mic.title")} description={t("voice.mic.description")}>
          {sources === null && !loading ? (
            <Row title={t("voice.mic.device")} leading={<Tile icon="mic" />}>
              <Skeleton className="h-8 w-56 rounded-md" />
            </Row>
          ) : sources && sources.length === 0 ? (
            <Row leading={<Tile icon="mic" />} title={t("voice.mic.device")} description={t("voice.mic.noList")}>
              <Badge tone="warn">{t("common.default")}</Badge>
            </Row>
          ) : (
            <SelectSetting
              leading={<Tile icon="mic" />}
              title={t("voice.mic.device")}
              description={t("voice.mic.deviceHint")}
              value={device}
              options={[
                { value: "", label: t("voice.mic.defaultInput") },
                ...(sources ?? []).map((source) => ({
                  value: source.name,
                  label: source.description || source.name,
                })),
              ]}
              onChange={(next) => void set("audio", "device", next)}
            />
          )}
          <Row
            leading={<Tile icon="wave" tone={monitoring ? "accent" : "muted"} />}
            title={t("voice.mic.level")}
            description={monitoring ? t("voice.mic.levelLive") : t("voice.mic.levelIdle")}
          >
            <LevelMeter active={monitoring} />
            <Button
              size="sm"
              variant={monitoring ? "secondary" : "primary"}
              icon={monitoring ? "square" : "play"}
              aria-pressed={monitoring}
              onClick={() => setMonitoring((value) => !value)}
            >
              {monitoring ? t("voice.mic.stopTest") : t("voice.mic.startTest")}
            </Button>
          </Row>
        </Section>

        <Section title={t("voice.stt.title")} description={t("voice.stt.description")}>
          <SelectSetting
            title={t("voice.stt.engine")}
            description={t("voice.stt.engineHint")}
            value={backend}
            options={STT_BACKENDS.map((item) => ({ value: item.value, label: optionLabel(item, t) }))}
            onChange={(next) => void set("stt", "backend", next)}
            extra={
              backendLink && backendDef ? (
                <LinkButton href={backendLink}>
                  {t("voice.stt.getEngine", { name: optionLabel(backendDef, t).split(" (")[0] })}
                </LinkButton>
              ) : undefined
            }
          />
          <ConfigText
            section="stt"
            k="model"
            title={t("voice.stt.model")}
            description={t("voice.stt.modelHint")}
            placeholder="ggml-small.en.bin"
            monospace
            width="w-56"
          />
          <ConfigText
            section="stt"
            k="language"
            title={t("voice.stt.language")}
            description={t("voice.stt.languageHint")}
            fallback="auto"
            placeholder="auto"
            monospace
            width="w-24"
          />
          <SttLanguageMismatch />
          <SelectSetting
            title={t("voice.stt.device")}
            description={t("voice.stt.deviceHint")}
            value={String(get("stt", "device", "cuda"))}
            options={STT_DEVICES.map((value) => ({ value, label: value === "cuda" ? "GPU (CUDA)" : value.toUpperCase() === "CPU" ? "CPU" : value }))}
            onChange={(next) => void set("stt", "device", next)}
          />
        </Section>

        <div className="flex items-start gap-3 rounded-lg bg-accent-soft px-4 py-3.5">
          <Icon name="sparkles" size={16} className="mt-0.5 shrink-0 text-accent-text" />
          <div>
            <div className="text-[13px] font-medium text-foreground">{t("voice.tip.title")}</div>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("voice.tip.body")}</p>
          </div>
        </div>
      </PageBody>
    </>
  );
}
