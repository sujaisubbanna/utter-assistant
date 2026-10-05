import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { humanizeError } from "../lib/errors";
import { useTauriEvent } from "../lib/events";
import { humanBytes, parseJsonLine } from "../lib/format";
import { inferenceReady, REQUIRED_SPEECH_SOURCE, useInferenceStatus } from "../lib/inference";
import { LINKS } from "../lib/links";
import type { InferenceStatus } from "../lib/types";
import { cn } from "../lib/utils";
import { Icon } from "./icons";
import { Button, LinkButton } from "./ui/Button";
import { Modal } from "./ui/Modal";
import { Progress } from "./ui/Progress";
import { Tile } from "./ui/Row";

type Phase = "idle" | "starting" | "downloading" | "done" | "error";
type Stage = "engine" | "speech";

/** The exact command both the consent panel and the backend use. */
const INSTALL_COMMAND = "assistant inference install --json";
const SPEECH_COMMAND = `assistant models pull ${REQUIRED_SPEECH_SOURCE}`;

/**
 * Download the models Utter requires, with consent and live progress.
 *
 * The vision + planner pair can't be pulled from the model store (UI-TARS is
 * sharded safetensors), so they are provisioned by `assistant inference
 * install`. The whisper.cpp speech model is a normal store pull. When
 * `includeSpeech` is set the dialog provisions whichever of the two is missing,
 * in order, reusing both progress channels. It shows what will be downloaded
 * and the exact command first, then the live output, then a real end state.
 */
export function InferenceInstallDialog({
  open,
  onClose,
  onInstalled,
  includeSpeech = false,
  engineReady = false,
  speechReady = false,
}: {
  open: boolean;
  onClose: () => void;
  onInstalled?: () => void;
  /** Also provision the required whisper.cpp speech model. */
  includeSpeech?: boolean;
  /** Whether the vision + planner runtime is already present. */
  engineReady?: boolean;
  /** Whether the required speech model is already present. */
  speechReady?: boolean;
}) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [stage, setStage] = useState<Stage>("engine");
  const [error, setError] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [downloaded, setDownloaded] = useState(0);
  const [total, setTotal] = useState<number | null>(null);
  const [fraction, setFraction] = useState(0);
  const installId = useRef("");
  const pullId = useRef("");
  const cancelled = useRef(false);

  const reset = useCallback(() => {
    setPhase("idle");
    setStage("engine");
    setError("");
    setLines([]);
    setDownloaded(0);
    setTotal(null);
    setFraction(0);
    installId.current = "";
    pullId.current = "";
    cancelled.current = false;
  }, []);

  // A fresh open starts over, unless a download from a previous visit is live.
  useEffect(() => {
    if (open && (phase === "done" || phase === "error")) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const startSpeech = useCallback(async () => {
    const id = `inference-speech-${Date.now()}`;
    pullId.current = id;
    cancelled.current = false;
    setStage("speech");
    setPhase("downloading");
    setError("");
    setDownloaded(0);
    setTotal(null);
    setFraction(0);
    try {
      await api.startModelsPull(id, REQUIRED_SPEECH_SOURCE, "latest");
    } catch (err) {
      setPhase("error");
      setError(humanizeError(err, t));
    }
  }, [t]);

  const startEngine = useCallback(async () => {
    const id = `inference-${Date.now()}`;
    installId.current = id;
    cancelled.current = false;
    setStage("engine");
    setPhase("starting");
    setError("");
    setLines([]);
    try {
      await api.startInferenceInstall(id);
    } catch (err) {
      installId.current = "";
      setPhase("error");
      setError(humanizeError(err, t));
    }
  }, [t]);

  const start = useCallback(() => {
    if (!engineReady) {
      void startEngine();
      return;
    }
    if (includeSpeech && !speechReady) {
      void startSpeech();
      return;
    }
    setPhase("done");
  }, [engineReady, includeSpeech, speechReady, startEngine, startSpeech]);

  useTauriEvent<{ id: string; line: string; event?: string | null }>(
    "inference://progress",
    (payload) => {
      if (payload.id !== installId.current) return;
      const outer = parseJsonLine(payload.line);
      const kind = String(payload.event ?? outer?.event ?? "");
      if (kind === "start") {
        setPhase("downloading");
        return;
      }
      if (kind === "progress") {
        const raw = String(outer?.line ?? "").trim();
        if (raw) setLines((prev) => [...prev.slice(-79), raw]);
        setPhase("downloading");
        return;
      }
      if (kind === "error") {
        setPhase("error");
        setError(humanizeError(outer?.error ?? "", t));
      }
      // A `done` line is followed by the process exit, which is authoritative.
    },
    open,
  );

  useTauriEvent<{ id: string; code: number }>(
    "inference://done",
    (payload) => {
      if (payload.id !== installId.current) return;
      if (cancelled.current) {
        reset();
        return;
      }
      if (payload.code === 0) {
        // The engine is in; if speech is also required, pull it before done.
        if (includeSpeech && !speechReady) {
          void startSpeech();
          return;
        }
        setPhase("done");
        onInstalled?.();
      } else {
        setPhase("error");
        setError((prev) => prev || t("models.inference.exitFailed", { code: payload.code }));
      }
    },
    open,
  );

  useTauriEvent<{ pullId: string; line: string }>(
    "models://progress",
    (payload) => {
      if (payload.pullId !== pullId.current) return;
      const event = parseJsonLine(payload.line);
      if (!event) return;
      if (event.event === "progress") {
        const done = Number(event.downloaded ?? 0);
        const size = event.total == null ? null : Number(event.total);
        setPhase("downloading");
        setDownloaded(done);
        setTotal(size);
        if (size) setFraction(Math.min(1, done / size));
      } else if (event.event === "done") {
        setFraction(1);
      } else if (event.event === "error") {
        setPhase("error");
        setError(humanizeError(event.error ?? "", t));
      }
    },
    open,
  );

  useTauriEvent<{ pullId: string; code: number }>(
    "models://done",
    (payload) => {
      if (payload.pullId !== pullId.current) return;
      if (payload.code === 0) {
        setPhase("done");
        setFraction(1);
        onInstalled?.();
      } else {
        setPhase("error");
        setError((prev) => prev || t("models.pull.exitFailed", { code: payload.code }));
      }
    },
    open,
  );

  const stop = async () => {
    cancelled.current = true;
    if (installId.current) await api.cancelInferenceInstall(installId.current).catch(() => {});
    if (pullId.current) await api.cancelModelsPull(pullId.current).catch(() => {});
    reset();
  };

  const downloading = phase === "downloading" || phase === "starting";

  let footer;
  if (downloading) {
    footer = (
      <>
        <Button variant="ghost" onClick={() => void stop()}>
          {t("models.inference.cancel")}
        </Button>
        <Button variant="primary" loading>
          {t("models.inference.downloading")}
        </Button>
      </>
    );
  } else if (phase === "error") {
    footer = (
      <>
        <Button variant="ghost" onClick={onClose}>
          {t("models.inference.notNow")}
        </Button>
        <Button variant="primary" icon="refresh" onClick={start}>
          {t("models.inference.retry")}
        </Button>
      </>
    );
  } else if (phase === "done") {
    footer = (
      <Button variant="primary" onClick={onClose}>
        {t("models.inference.done")}
      </Button>
    );
  } else {
    footer = (
      <>
        <LinkButton href={LINKS.uitars} variant="ghost">
          {t("models.inference.website")}
        </LinkButton>
        <Button variant="ghost" onClick={onClose}>
          {t("models.inference.notNow")}
        </Button>
        <Button variant="primary" icon="download" onClick={start}>
          {t("models.inference.start")}
        </Button>
      </>
    );
  }

  const title = includeSpeech
    ? t("models.inference.requiredTitle")
    : t("models.inference.consentTitle");
  const description = includeSpeech
    ? t("models.inference.requiredDescription")
    : t("models.inference.consentBody", { size: t("models.inference.totalSize") });
  const command = includeSpeech && engineReady ? SPEECH_COMMAND : INSTALL_COMMAND;

  return (
    <Modal open={open} onClose={onClose} title={title} description={description} size="md" footer={footer}>
      {phase === "done" ? (
        <div className="flex items-start gap-3 rounded-lg px-4 py-3.5 [background:color-mix(in_oklab,var(--success)_10%,var(--card))] [box-shadow:0_0_0_1px_color-mix(in_oklab,var(--success)_28%,transparent)]">
          <Tile icon="check-circle" tone="ok" />
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-foreground">{t("models.inference.doneTitle")}</div>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("models.inference.doneBody")}</p>
          </div>
        </div>
      ) : downloading ? (
        <div className="space-y-3">
          <div className="animate-fade-up space-y-2 bg-wash px-4 py-3.5">
            <div className="flex items-center justify-between gap-4 text-xs">
              <span className="min-w-0 truncate font-medium text-foreground">
                {stage === "speech"
                  ? t("models.inference.speech")
                  : phase === "starting"
                    ? t("models.inference.starting")
                    : t("models.inference.downloading")}
              </span>
              {stage === "speech" && downloaded > 0 && (
                <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
                  {total
                    ? t("models.pull.progress", { done: humanBytes(downloaded), total: humanBytes(total) })
                    : humanBytes(downloaded)}
                </span>
              )}
            </div>
            {stage === "speech" ? (
              <Progress label={t("models.pull.downloading")} value={fraction} indeterminate={!total} />
            ) : (
              <Progress label={t("models.inference.downloading")} indeterminate />
            )}
          </div>
          {stage === "engine" && lines.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("models.inference.activity")}
              </div>
              <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded-lg bg-wash px-3.5 py-3 font-mono text-[11px] leading-[17px] text-muted-foreground shadow-[inset_0_0_0_1px_var(--line)] [overflow-wrap:anywhere]">
                {lines.join("\n")}
              </pre>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {phase === "error" && (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-lg px-4 py-3.5 [background:color-mix(in_oklab,var(--destructive)_6%,transparent)] [box-shadow:0_0_0_1px_color-mix(in_oklab,var(--destructive)_28%,transparent)]"
            >
              <Tile icon="alert" tone="danger" />
              <div className="min-w-0">
                <div className="text-[13px] font-medium text-foreground">{t("models.inference.failedTitle")}</div>
                <p className="mt-0.5 text-xs text-muted-foreground">{t("models.inference.failedBody")}</p>
                {error && (
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                    {error}
                  </p>
                )}
              </div>
            </div>
          )}

          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("models.inference.willDownload")}
          </div>
          <div className="divide-y divide-line overflow-hidden rounded-lg bg-card shadow-card">
            {includeSpeech && !speechReady && (
              <InferencePart
                icon="mic"
                title={t("models.inference.speech")}
                model={t("models.inference.speechModel")}
                size={t("models.inference.speechSize")}
                required
              />
            )}
            {!engineReady && (
              <>
                <InferencePart
                  icon="eye"
                  title={t("models.inference.vision")}
                  model={t("models.inference.visionModel")}
                  size={t("models.inference.visionSize")}
                />
                <InferencePart
                  icon="sparkles"
                  title={t("models.inference.planner")}
                  model={t("models.inference.plannerModel")}
                  size={t("models.inference.plannerSize")}
                />
              </>
            )}
          </div>

          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("models.inference.commandLabel")}
          </div>
          <div className="flex items-center gap-3 rounded-lg bg-wash px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]">
            <Icon name="terminal" size={15} className="shrink-0 text-muted-foreground" />
            <code className="min-w-0 flex-1 select-all break-all font-mono text-[12px] text-foreground">
              {command}
            </code>
          </div>

          <p className="flex items-start gap-1.5 px-0.5 text-[11.5px] text-muted-foreground/85">
            <Icon name="info" size={13} className="mt-px shrink-0" />
            {t("models.inference.note")}
          </p>
        </div>
      )}
    </Modal>
  );
}

function InferencePart({
  icon,
  title,
  model,
  size,
  required,
}: {
  icon: "eye" | "sparkles" | "mic";
  title: string;
  model: string;
  size: string;
  required?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <Tile icon={icon} tone="accent" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13px] font-medium text-foreground">
          {title}
          {required && <span className="text-[11px] font-medium text-accent-text">{t("models.inference.required")}</span>}
        </div>
        <div className="mt-0.5 truncate font-mono text-[11.5px] text-muted-foreground">{model}</div>
      </div>
      <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">{size}</span>
    </div>
  );
}

/**
 * The "Download vision + planner models" action. Opens the consent/progress
 * dialog above. Available on every platform: the installer sets up the right
 * runtime for the host (torch + transformers on Windows/macOS, vLLM on Linux).
 *
 * Pass `status` when the caller already tracks the models; otherwise this reads
 * it itself so it can label the button (Download vs Download again).
 */
export function InferenceInstallButton({
  status,
  onInstalled,
  size = "md",
  variant = "primary",
}: {
  status?: InferenceStatus | null;
  onInstalled?: () => void;
  size?: "sm" | "md";
  variant?: "primary" | "secondary";
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const internal = useInferenceStatus();
  const resolved = status !== undefined ? status : internal.status;
  const ready = inferenceReady(resolved);

  return (
    <>
      <Button size={size} variant={variant} icon="download" onClick={() => setOpen(true)}>
        {ready ? t("models.inference.redownload") : t("models.inference.download")}
      </Button>
      <InferenceInstallDialog
        open={open}
        onClose={() => setOpen(false)}
        onInstalled={() => {
          void internal.refresh();
          onInstalled?.();
        }}
      />
    </>
  );
}

/**
 * The settings home for the missing-runtime state: a status card with an
 * Install / repair action. Renders nothing until the probe answers and nothing
 * once the vision + planner runtime and the required speech model are present,
 * so it can be dropped in unconditionally.
 *
 * It stays hidden while the status is unknown (for example when the Python
 * engine itself is missing) because `EngineInstallCard` owns that state.
 */
export function InferenceInstallCard({ className }: { className?: string }) {
  const { t } = useI18n();
  const { status, speech, loading, refresh } = useInferenceStatus();
  const [open, setOpen] = useState(false);
  if (loading || !status) return null;

  const engineMissing = !inferenceReady(status);
  if (!engineMissing && speech) return null;

  return (
    <section
      className={cn("relative overflow-hidden rounded-lg bg-card p-5 shadow-card", className)}
      aria-live="polite"
    >
      <div className="flex items-start gap-4">
        <span
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
          style={{
            color: "var(--primary)",
            background: "color-mix(in oklab, var(--primary) 13%, transparent)",
          }}
        >
          <Icon name={engineMissing ? "eye" : "mic"} size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold text-foreground">{t("models.inference.requiredTitle")}</span>
            <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent-text">
              {t("models.inference.required")}
            </span>
          </div>
          <p className="mt-1 max-w-[44rem] text-xs leading-[18px] text-muted-foreground">
            {t("models.inference.requiredDescription")}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" icon="download" onClick={() => setOpen(true)}>
              {t("models.inference.repair")}
            </Button>
            <LinkButton href={LINKS.uitars} variant="ghost">
              {t("models.inference.website")}
            </LinkButton>
          </div>
        </div>
      </div>
      <InferenceInstallDialog
        open={open}
        onClose={() => setOpen(false)}
        includeSpeech
        engineReady={!engineMissing}
        speechReady={speech}
        onInstalled={() => void refresh()}
      />
    </section>
  );
}
