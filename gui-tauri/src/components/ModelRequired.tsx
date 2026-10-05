import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n, type MessageKey } from "../i18n";
import { api } from "../lib/api";
import { useTauriEvent } from "../lib/events";
import { humanizeError } from "../lib/errors";
import { humanBytes, parseJsonLine } from "../lib/format";
import { useModelStatus, type ModelKind, type ModelNeed } from "../lib/models";
import { Icon } from "./icons";
import { InferenceInstallButton } from "./InferenceInstall";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";
import { Progress } from "./ui/Progress";
import { Tile } from "./ui/Row";

type Phase = "idle" | "starting" | "downloading" | "done" | "error";

const BODY_KEY: Record<ModelKind, MessageKey> = {
  stt: "modelRequired.sttBody",
  vision: "modelRequired.visionBody",
};

/**
 * "You need a model first" — shown when a feature needs a model the store
 * doesn't have. Downloads through the existing pull command (only when the
 * store has a source for the model), with progress and a real error, and
 * always offers the Models page as the fallback path.
 */
export function ModelRequiredDialog({
  open,
  onClose,
  need,
  modelsPath,
  onInstalled,
}: {
  open: boolean;
  onClose: () => void;
  need: ModelNeed | null;
  modelsPath: string;
  /** Called once when a download finishes, so the caller can apply the model. */
  onInstalled?: () => void;
}) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [downloaded, setDownloaded] = useState(0);
  const [total, setTotal] = useState<number | null>(null);
  const [fraction, setFraction] = useState(0);
  const [indeterminate, setIndeterminate] = useState(false);
  const pullId = useRef("");

  const reset = useCallback(() => {
    setPhase("idle");
    setError("");
    setDownloaded(0);
    setTotal(null);
    setFraction(0);
    setIndeterminate(false);
  }, []);

  // A fresh open starts over, unless a download from a previous visit is still running.
  useEffect(() => {
    if (open && (phase === "done" || phase === "error")) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useTauriEvent<{ pullId: string; line: string }>(
    "models://progress",
    (payload) => {
      if (payload.pullId !== pullId.current) return;
      const event = parseJsonLine(payload.line);
      if (!event) return;
      const kind = event.event;
      if (kind === "start") {
        setPhase("downloading");
        setIndeterminate(true);
      } else if (kind === "progress") {
        const done = Number(event.downloaded ?? 0);
        const size = event.total == null ? null : Number(event.total);
        setPhase("downloading");
        setDownloaded(done);
        setTotal(size);
        setIndeterminate(size == null);
        if (size) setFraction(Math.min(1, done / size));
      } else if (kind === "done") {
        setFraction(1);
        setIndeterminate(false);
        setDownloaded(Number(event.bytes ?? 0));
      } else if (kind === "error") {
        setPhase("error");
        setIndeterminate(false);
        setError(humanizeError(event.error ?? "", t));
      }
    },
    open,
  );

  useTauriEvent<{ pullId: string; code: number }>(
    "models://done",
    (payload) => {
      if (payload.pullId !== pullId.current) return;
      setIndeterminate(false);
      if (payload.code === 0) {
        setPhase("done");
        setFraction(1);
        onInstalled?.();
      } else {
        setPhase("error");
        setError((prev) => prev || t("modelRequired.failedBody"));
      }
    },
    open,
  );

  if (!need) return null;

  const start = async () => {
    if (!need.source) return;
    const id = `model-required-${Date.now()}`;
    pullId.current = id;
    setPhase("starting");
    setError("");
    setDownloaded(0);
    setTotal(null);
    setFraction(0);
    setIndeterminate(true);
    try {
      await api.startModelsPull(id, need.source, "latest");
    } catch (err) {
      setPhase("error");
      setIndeterminate(false);
      setError(String((err as Error)?.message ?? err));
    }
  };

  const stop = async () => {
    if (pullId.current) await api.cancelModelsPull(pullId.current).catch(() => {});
    reset();
  };

  const openModels = () => {
    window.location.hash = "/models";
    onClose();
  };

  const downloading = phase === "downloading" || phase === "starting";

  let footer;
  if (downloading) {
    footer = (
      <>
        <Button variant="ghost" onClick={() => void stop()}>
          {t("modelRequired.stop")}
        </Button>
        <Button variant="primary" loading>
          {t("modelRequired.downloading")}
        </Button>
      </>
    );
  } else if (phase === "error") {
    footer = (
      <>
        <Button variant="ghost" onClick={onClose}>
          {t("modelRequired.notNow")}
        </Button>
        <Button variant="primary" icon="refresh" onClick={() => void start()}>
          {t("modelRequired.retry")}
        </Button>
      </>
    );
  } else if (phase === "done") {
    footer = (
      <Button variant="primary" onClick={onClose}>
        {t("modelRequired.done")}
      </Button>
    );
  } else {
    footer = (
      <>
        <Button variant="ghost" onClick={onClose}>
          {t("modelRequired.notNow")}
        </Button>
        {need.source ? (
          <Button variant="primary" icon="download" onClick={() => void start()}>
            {t("modelRequired.download")}
          </Button>
        ) : need.kind === "vision" ? (
          <InferenceInstallButton onInstalled={onInstalled} />
        ) : (
          <Button variant="primary" icon="sliders" onClick={openModels}>
            {t("modelRequired.openModels")}
          </Button>
        )}
      </>
    );
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("modelRequired.title")}
      description={t(BODY_KEY[need.kind])}
      size="md"
      footer={footer}
    >
      {downloading ? (
        <div className="space-y-3">
          <ModelCard need={need} />
          <div className="animate-fade-up space-y-2 rounded-lg bg-wash px-4 py-3.5">
            <div className="flex items-center justify-between gap-4 text-xs">
              <span className="min-w-0 truncate font-medium text-foreground">
                {phase === "starting" ? t("modelRequired.starting") : t("modelRequired.downloading")}
              </span>
              <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
                {downloaded > 0
                  ? total
                    ? t("modelRequired.progress", {
                        done: humanBytes(downloaded),
                        total: humanBytes(total),
                      })
                    : humanBytes(downloaded)
                  : ""}
              </span>
            </div>
            <Progress
              label={t("modelRequired.downloading")}
              value={fraction}
              indeterminate={indeterminate}
            />
          </div>
        </div>
      ) : phase === "done" ? (
        <div className="flex items-start gap-3 rounded-lg px-4 py-3.5 [background:color-mix(in_oklab,var(--success)_10%,var(--card))] [box-shadow:0_0_0_1px_color-mix(in_oklab,var(--success)_28%,transparent)]">
          <Tile icon="check-circle" tone="ok" />
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-foreground">
              {t("modelRequired.doneTitle")}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("modelRequired.doneBody", { name: need.model })}
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <ModelCard need={need} />

          <div className="flex items-center gap-3 rounded-lg bg-card px-4 py-3 shadow-card">
            <Tile icon="folder" />
            <div className="min-w-0 flex-1">
              <div className="text-xs text-muted-foreground">{t("modelRequired.storeLabel")}</div>
              <div className="truncate font-mono text-[11.5px] text-foreground" title={modelsPath}>
                {modelsPath}
              </div>
            </div>
          </div>

          {phase === "error" && (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-lg px-4 py-3.5 [background:color-mix(in_oklab,var(--destructive)_6%,transparent)] [box-shadow:0_0_0_1px_color-mix(in_oklab,var(--destructive)_28%,transparent)]"
            >
              <Tile icon="alert" tone="danger" />
              <div className="min-w-0">
                <div className="text-[13px] font-medium text-foreground">
                  {t("modelRequired.failedTitle")}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {t("modelRequired.failedBody")}
                </p>
                {error && (
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                    {error}
                  </p>
                )}
              </div>
            </div>
          )}

          {need.estimated && (
            <Note>{t("modelRequired.estimatedNote")}</Note>
          )}
          {need.kind === "stt" && <Note>{t("modelRequired.sttNote")}</Note>}
          {need.kind === "vision" && !need.source && <Note>{t("modelRequired.shardedNote")}</Note>}
        </div>
      )}
    </Modal>
  );
}

function ModelCard({ need }: { need: ModelNeed }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 rounded-lg bg-wash px-4 py-3.5">
      <Tile icon={need.kind === "stt" ? "mic" : "eye"} tone="accent" />
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[12.5px] font-medium text-foreground">
          {need.model}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {need.size
            ? t("modelRequired.size", { size: humanBytes(need.size) })
            : t("common.unknown")}
        </div>
      </div>
      <Badge tone="accent">{t("modelRequired.recommended")}</Badge>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 px-0.5 text-[11.5px] text-muted-foreground/85">
      <Icon name="info" size={13} className="mt-px shrink-0" />
      {children}
    </p>
  );
}

/**
 * A contextual callout for a page whose feature needs a missing model. Renders
 * nothing while the state is unknown or the model is present.
 */
export function ModelRequiredBanner({ kind }: { kind: ModelKind }) {
  const { t } = useI18n();
  const { need, storePath, models } = useModelStatus();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  const target = need(kind);
  // Speech models are fetched by the engine, not stored here, so the speech
  // card is only a first-run nudge for an otherwise empty store.
  const relevant =
    target !== null && !target.installed && (kind !== "stt" || models.length === 0);
  if (!relevant || !target) return null;

  return (
    <>
      <section
        aria-labelledby={`model-required-${kind}`}
        className="relative overflow-hidden rounded-xl bg-card shadow-card"
        style={{
          boxShadow:
            "0 0 0 1px color-mix(in oklab, var(--primary) 30%, var(--line)), 0 1px 2px rgb(0 0 0 / 0.05), 0 12px 32px -18px color-mix(in oklab, var(--primary) 45%, transparent)",
        }}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(120% 90% at 0% 0%, color-mix(in oklab, var(--primary) 12%, transparent), transparent 60%)",
          }}
        />
        <div className="relative flex items-start gap-4 px-5 py-4 max-[600px]:flex-col">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
            <Icon name={kind === "stt" ? "mic" : "eye"} size={20} strokeWidth={1.7} />
          </span>
          <div className="min-w-0 flex-1">
            <h2
              id={`model-required-${kind}`}
              className="text-[15px] font-semibold tracking-[-0.01em] text-foreground"
            >
              {t("modelRequired.title")}
            </h2>
            <p className="mt-0.5 max-w-[34rem] text-xs text-muted-foreground">
              {t(BODY_KEY[kind])}
            </p>
          </div>
          <Button
            variant="primary"
            icon="download"
            onClick={() => setOpen(true)}
            className="max-[600px]:w-full"
          >
            {t("modelRequired.action")}
          </Button>
        </div>
      </section>
      <ModelRequiredDialog
        open={open}
        onClose={close}
        need={target}
        modelsPath={storePath}
      />
    </>
  );
}
