import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { humanizeError } from "../lib/errors";
import { useTauriEvent } from "../lib/events";
import { parseJsonLine } from "../lib/format";
import { inferenceReady, useInferenceStatus } from "../lib/inference";
import { LINKS } from "../lib/links";
import { usePlatform } from "../lib/platform";
import type { InferenceStatus } from "../lib/types";
import { Icon } from "./icons";
import { Button, LinkButton } from "./ui/Button";
import { Modal } from "./ui/Modal";
import { Progress } from "./ui/Progress";
import { Tile } from "./ui/Row";

type Phase = "idle" | "starting" | "downloading" | "done" | "error";

/** The exact command both the consent panel and the backend use. */
const INSTALL_COMMAND = "assistant inference install --json";

/**
 * Download the sharded vision + planner models with consent and live progress.
 *
 * The model store can't pull these (UI-TARS is sharded safetensors), so they
 * are provisioned by `assistant inference install`, which the backend streams
 * back over `inference://progress`. This dialog shows what will be downloaded
 * and the exact command first, then the live output, then a real end state.
 */
export function InferenceInstallDialog({
  open,
  onClose,
  onInstalled,
}: {
  open: boolean;
  onClose: () => void;
  onInstalled?: () => void;
}) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const installId = useRef("");
  const cancelled = useRef(false);

  const reset = useCallback(() => {
    setPhase("idle");
    setError("");
    setLines([]);
    installId.current = "";
    cancelled.current = false;
  }, []);

  // A fresh open starts over, unless a download from a previous visit is live.
  useEffect(() => {
    if (open && (phase === "done" || phase === "error")) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

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
        setPhase("done");
        onInstalled?.();
      } else {
        setPhase("error");
        setError((prev) => prev || t("models.inference.exitFailed", { code: payload.code }));
      }
    },
    open,
  );

  const start = async () => {
    const id = `inference-${Date.now()}`;
    installId.current = id;
    cancelled.current = false;
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
  };

  const stop = async () => {
    cancelled.current = true;
    if (installId.current) await api.cancelInferenceInstall(installId.current).catch(() => {});
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
        <Button variant="primary" icon="refresh" onClick={() => void start()}>
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
        <Button variant="primary" icon="download" onClick={() => void start()}>
          {t("models.inference.start")}
        </Button>
      </>
    );
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("models.inference.consentTitle")}
      description={t("models.inference.consentBody", { size: t("models.inference.totalSize") })}
      size="md"
      footer={footer}
    >
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
                {phase === "starting" ? t("models.inference.starting") : t("models.inference.downloading")}
              </span>
            </div>
            <Progress label={t("models.inference.downloading")} indeterminate />
          </div>
          {lines.length > 0 && (
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
          </div>

          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("models.inference.commandLabel")}
          </div>
          <div className="flex items-center gap-3 rounded-lg bg-wash px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]">
            <Icon name="terminal" size={15} className="shrink-0 text-muted-foreground" />
            <code className="min-w-0 flex-1 select-all break-all font-mono text-[12px] text-foreground">
              {INSTALL_COMMAND}
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
}: {
  icon: "eye" | "sparkles";
  title: string;
  model: string;
  size: string;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <Tile icon={icon} tone="accent" />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-foreground">{title}</div>
        <div className="mt-0.5 truncate font-mono text-[11.5px] text-muted-foreground">{model}</div>
      </div>
      <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">{size}</span>
    </div>
  );
}

/**
 * The "Download vision + planner models" action. Opens the consent/progress
 * dialog above. Hidden behind a disabled button on Windows, where the installer
 * isn't supported yet.
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
  const { os } = usePlatform();
  const [open, setOpen] = useState(false);
  const internal = useInferenceStatus();
  const resolved = status !== undefined ? status : internal.status;
  const ready = inferenceReady(resolved);
  const unsupported = os === "windows";

  const button = (
    <Button
      size={size}
      variant={variant}
      icon="download"
      disabled={unsupported}
      onClick={() => setOpen(true)}
    >
      {ready ? t("models.inference.redownload") : t("models.inference.download")}
    </Button>
  );

  return (
    <>
      {unsupported ? (
        <span title={t("models.inference.unsupported")} className="inline-flex">
          {button}
        </span>
      ) : (
        button
      )}
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
