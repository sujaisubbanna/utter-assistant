import { useEffect, useState } from "react";

import { Icon } from "../components/icons";
import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigSwitch, ConfigText, SelectSetting } from "../components/Setting";
import { DepInstallButton } from "../components/DepInstall";
import { Badge } from "../components/ui/Badge";
import { Button, LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Modal } from "../components/ui/Modal";
import { Row, Tile } from "../components/ui/Row";
import { useT } from "../i18n";
import { useConfig } from "../lib/config";
import { displayMacKey, domCodeToMacKey, isMacModifier } from "../lib/keys";
import { linkFor } from "../lib/links";
import { MAC_HOTKEY_BACKENDS, MAC_STT_BACKENDS, optionLabel } from "../lib/services";

/**
 * The Voice page as it appears on macOS. Everything here writes the `[macos]`
 * section (plus the shared `[stt] model` for whisper), so the Linux keys and
 * their evdev names are never touched from a Mac.
 */

function MacKeyCaptureModal({
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
  onCaptured: (name: string) => void;
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
      const name = domCodeToMacKey(event.code);
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
          <p className="mt-1 text-xs text-muted-foreground">{t("voice.mac.escape")}</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {t("voice.keys.current")}
          <span className="kbd">{current ? displayMacKey(current) : t("voice.keys.notSet")}</span>
        </div>
        {preview && <p className="text-xs text-[color:var(--warning)]">{preview}</p>}
      </div>
    </Modal>
  );
}

function MacKeyRow({ title, description, field }: { title: string; description: string; field: string }) {
  const t = useT();
  const { get, set } = useConfig();
  const [open, setOpen] = useState(false);
  const current = String(get("macos", field, field === "assistant_key" ? "right_command" : "right_option"));
  return (
    <Row title={title} description={description} leading={<Tile icon="keyboard" />}>
      {current && isMacModifier(current) && <Badge tone="muted">{t("voice.keys.modifier")}</Badge>}
      <span className="kbd">{current ? displayMacKey(current) : t("voice.keys.notSet")}</span>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("voice.keys.change")}
      </Button>
      <MacKeyCaptureModal
        open={open}
        title={title}
        current={current}
        onClose={() => setOpen(false)}
        onCaptured={(name) => void set("macos", field, name)}
      />
    </Row>
  );
}

export function VoiceMacPage() {
  const t = useT();
  const { get, set } = useConfig();

  const backend = String(get("macos", "stt_backend", "apple_speech"));
  const fallback = String(get("macos", "stt_fallback", "whisper_cpp"));
  const backendDef = MAC_STT_BACKENDS.find((item) => item.value === backend);
  const backendLink = backendDef?.link ? linkFor(backendDef.link) : undefined;
  const usesWhisper = [backend, fallback].some((value) => value === "whisper_cpp" || value === "faster_whisper");
  const usesApple = [backend, fallback].includes("apple_speech");

  return (
    <>
      <PageHeader title={t("voice.title")} description={t("voice.mac.description")} />
      <PageBody config>
        <Section title={t("voice.keys.title")} description={t("voice.mac.keysDescription")}>
          <MacKeyRow title={t("voice.keys.assistant")} description={t("voice.keys.assistantHint")} field="assistant_key" />
          <MacKeyRow title={t("voice.keys.dictation")} description={t("voice.keys.dictationHint")} field="dictation_key" />
          <SelectSetting
            title={t("voice.mac.hotkeyBackend")}
            description={t("voice.mac.hotkeyBackendHint")}
            value={String(get("macos", "hotkey_backend", "quartz"))}
            options={MAC_HOTKEY_BACKENDS.map((item) => ({ value: item.value, label: optionLabel(item, t) }))}
            onChange={(next) => void set("macos", "hotkey_backend", next)}
          />
        </Section>

        <Section title={t("voice.stt.title")} description={t("voice.mac.sttDescription")}>
          <SelectSetting
            title={t("voice.stt.engine")}
            description={t("voice.mac.engineHint")}
            value={backend}
            options={MAC_STT_BACKENDS.map((item) => ({ value: item.value, label: optionLabel(item, t) }))}
            onChange={(next) => void set("macos", "stt_backend", next)}
            extra={
              backendLink && backendDef ? (
                <div className="flex items-center gap-2">
                  <DepInstallButton
                    dep={backend}
                    title={optionLabel(backendDef, t).split(" (")[0]}
                    href={backendLink}
                  />
                  <LinkButton href={backendLink}>
                    {t("voice.stt.getEngine", { name: optionLabel(backendDef, t).split(" (")[0] })}
                  </LinkButton>
                </div>
              ) : undefined
            }
          />
          <SelectSetting
            title={t("voice.mac.fallback")}
            description={t("voice.mac.fallbackHint")}
            value={fallback}
            options={[
              ...MAC_STT_BACKENDS.filter((item) => item.value !== backend).map((item) => ({
                value: item.value,
                label: optionLabel(item, t),
              })),
              { value: "none", label: t("common.none") },
            ]}
            onChange={(next) => void set("macos", "stt_fallback", next)}
          />
          {usesApple && (
            <>
              <ConfigText
                section="macos"
                k="speech_locale"
                title={t("voice.mac.locale")}
                description={t("voice.mac.localeHint")}
                fallback="en-US"
                monospace
                width="w-28"
              />
              <ConfigSwitch
                section="macos"
                k="on_device_only"
                title={t("voice.mac.onDevice")}
                description={t("voice.mac.onDeviceHint")}
              />
            </>
          )}
          {usesWhisper && (
            <ConfigText
              section="stt"
              k="model"
              title={t("voice.stt.model")}
              description={t("voice.mac.modelHint")}
              placeholder="small.en"
              monospace
              width="w-56"
            />
          )}
        </Section>

        <Section title={t("voice.mic.title")} description={t("voice.mac.micDescription")}>
          <ConfigText
            section="audio"
            k="device"
            title={t("voice.mic.device")}
            description={t("voice.mac.deviceHint")}
            placeholder={t("voice.mic.defaultInput")}
            width="w-56"
          />
        </Section>

        <div className="flex items-start gap-3 rounded-lg bg-accent-soft px-4 py-3.5">
          <Icon name="sparkles" size={16} className="mt-0.5 shrink-0 text-accent-text" />
          <div>
            <div className="text-[13px] font-medium text-foreground">{t("voice.tip.title")}</div>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("voice.mac.tip")}</p>
          </div>
        </div>
      </PageBody>
    </>
  );
}
