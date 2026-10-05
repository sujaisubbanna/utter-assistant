import { memo, useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "../components/icons";
import { PageBody, PageHeader } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Row, Tile } from "../components/ui/Row";
import { Select } from "../components/ui/Select";
import { SkeletonRows } from "../components/ui/Skeleton";
import { StatusDot } from "../components/ui/StatusDot";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { humanizeError } from "../lib/errors";
import { useTauriEvent } from "../lib/events";
import { usePlatform } from "../lib/platform";
import { servicesFor } from "../lib/services";
import { cn } from "../lib/utils";
import type { DoctorReport } from "../lib/types";

const MAX_LINES = 2000;
// Let the buffer overshoot, then trim back in one step. Rebuilding the whole
// list on every line once it is full is what made a followed tail feel heavy.
const TRIM_CHUNK = 500;

/**
 * One log line. Memoised so appending a tail line only renders the new node
 * instead of re-reconciling the whole (up to 2000-line) buffer.
 */
const LogLine = memo(function LogLine({ text }: { text: string }) {
  return <div>{text}</div>;
});

/** Capability names reported by `doctor` -> `compositor.capabilities` (see utter/context/compositor.py). */
const CAP_KEYS = {
  focused_window: true,
  list_windows: true,
  activate: true,
  close: true,
  minimize: true,
  maximize: true,
  move_to_workspace: true,
  switch_workspace: true,
  screenshot: true,
  compositor_action: true,
} as const;
type CapKey = keyof typeof CAP_KEYS;

export function DiagnosticsPage() {
  const { t, tn } = useI18n();
  const { isMac } = usePlatform();
  const toast = useToast();
  const services = servicesFor(isMac);
  const [unit, setUnit] = useState("utter-runner");
  const [follow, setFollow] = useState(true);
  const [lines, setLines] = useState<string[]>([]);
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [doctorLoading, setDoctorLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [hideUnavailable, setHideUnavailable] = useState(false);
  const tailId = useRef("");
  const viewRef = useRef<HTMLDivElement>(null);

  const stopTail = useCallback(() => {
    if (tailId.current) {
      void api.stopLogTail(tailId.current).catch(() => {});
      tailId.current = "";
    }
  }, []);

  const startTail = useCallback(() => {
    stopTail();
    const id = `tail-${unit}-${Date.now()}`;
    tailId.current = id;
    setLines([]);
    api
      .startLogTail(unit, id)
      .catch((error) =>
        toast(t("diagnostics.logs.tailFailed", { error: humanizeError(error, t) }), "error"),
      );
  }, [stopTail, toast, unit, t]);

  useEffect(() => {
    if (follow) startTail();
    else stopTail();
    return () => stopTail();
  }, [follow, startTail, stopTail]);

  useTauriEvent<{ tailId: string; line: string }>(
    "log://line",
    (payload) => {
      if (payload.tailId !== tailId.current) return;
      setLines((current) => {
        const next = [...current, payload.line];
        return next.length > MAX_LINES + TRIM_CHUNK ? next.slice(next.length - MAX_LINES) : next;
      });
    },
    follow,
  );

  useEffect(() => {
    const node = viewRef.current;
    if (!node) return;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 60;
    if (nearBottom) node.scrollTop = node.scrollHeight;
  }, [lines]);

  const runDoctor = useCallback(async () => {
    setDoctorLoading(true);
    try {
      setReport(await api.doctor());
    } catch (error) {
      setReport({ ok: false, connected: false, error: humanizeError(error, t), plugins: [] });
    } finally {
      setDoctorLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void runDoctor();
  }, [runDoctor]);

  const exportBundle = async () => {
    setExporting(true);
    try {
      const result = await api.exportBundle();
      toast(t("diagnostics.bundle.done", { path: result.path }), "ok");
    } catch (error) {
      toast(t("diagnostics.bundle.failed", { error: humanizeError(error, t) }), "error");
    } finally {
      setExporting(false);
    }
  };

  const copyLogs = async () => {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      toast(t("diagnostics.logs.copied"), "ok");
    } catch {
      toast(t("diagnostics.logs.copyFailed"), "error");
    }
  };

  const runner = report?.runner ?? {};
  const compositor = report?.compositor;
  const caps = compositor?.capabilities ?? {};
  const capNames = Object.keys(caps);
  const unavailableCount = capNames.filter((name) => !caps[name]).length;
  const visibleCaps = hideUnavailable ? capNames.filter((name) => caps[name]) : capNames;
  const backendLabel = (name?: string) => {
    const key = (name ?? "unknown") as "niri" | "kwin" | "unknown";
    return key === "niri" || key === "kwin" ? t(`diagnostics.desktop.names.${key}`) : t("diagnostics.desktop.names.unknown");
  };

  return (
    <>
      <PageHeader title={t("diagnostics.title")} description={t("diagnostics.description")} />
      <PageBody>
        <Section
          title={t("diagnostics.health.title")}
          description={t("diagnostics.health.description")}
          actions={
            <Button size="sm" variant="ghost" icon="refresh" loading={doctorLoading} onClick={() => void runDoctor()}>
              {t("diagnostics.health.run")}
            </Button>
          }
        >
          {report === null ? (
            <SkeletonRows count={3} />
          ) : (
            <>
              <Row
                leading={<Tile icon={report.ok ? "check-circle" : "alert"} tone={report.ok ? "ok" : "warn"} />}
                title={t("diagnostics.health.overall")}
                description={report.ok ? t("diagnostics.health.allGood") : humanizeError(report.error, t) || t("diagnostics.health.issues")}
              >
                <Badge tone={report.ok ? "ok" : "warn"} dot>
                  {report.ok ? t("plugins.runner.healthy") : t("plugins.runner.issues")}
                </Badge>
              </Row>
              <Row
                leading={
                  <span className="flex w-7 justify-center">
                    <StatusDot tone={report.connected ? "ok" : "error"} />
                  </span>
                }
                title={t("diagnostics.health.core")}
                description={
                  <span className="font-mono text-[11.5px]">
                    {t("diagnostics.health.coreDetail", {
                      version: runner.version ?? "?",
                      protocol: `${runner.protocol ?? "?"} · abi ${runner.abi ?? "?"}`,
                    })}
                  </span>
                }
              />
              <Row
                as="button"
                onClick={() => setShowRaw((value) => !value)}
                leading={<Tile icon="terminal" />}
                title={t("diagnostics.health.raw")}
                description={t("diagnostics.health.rawHint")}
              >
                <Icon
                  name="chevron-down"
                  size={15}
                  aria-hidden="true"
                  className={cn("text-muted-foreground transition-transform duration-150 ease-out", showRaw && "rotate-180")}
                />
              </Row>
              {showRaw && (
                <div className="animate-fade-up bg-wash px-4 py-3">
                  <pre className="max-h-72 overflow-auto font-mono text-[11px] leading-relaxed text-foreground/85">
                    {JSON.stringify(report, null, 2)}
                  </pre>
                </div>
              )}
            </>
          )}
        </Section>

        {report?.runtime && (
          <Section
            title="Inference & runtime"
            description="Local model runners, speech recognition, and acceleration detected on this machine."
          >
            <Row
              leading={<Tile icon="sparkles" tone={report.runtime.gpu?.available ? "accent" : "muted"} />}
              title={report.runtime.gpu?.name ?? "GPU"}
              description={report.runtime.device ? `Runtime: ${report.runtime.device.toUpperCase()}${report.runtime.gpu?.unified_memory_gb ? ` · ${report.runtime.gpu.unified_memory_gb} GB unified memory` : ""}` : undefined}
            >
              <Badge tone={report.runtime.gpu?.available ? "ok" : "muted"}>
                {report.runtime.device?.toUpperCase() ?? "UNKNOWN"}
              </Badge>
            </Row>
            {report.runtime.llm && (
              <Row
                leading={<Tile icon="cpu" tone={report.runtime.llm.available ? "ok" : "warn"} />}
                title={`LLM (${report.runtime.llm.provider ?? "server"})`}
                description={report.runtime.llm.message || `${report.runtime.llm.model} @ ${report.runtime.llm.endpoint}`}
              >
                <Badge tone={report.runtime.llm.available ? "ok" : "warn"}>
                  {report.runtime.llm.status ?? "unknown"}
                </Badge>
              </Row>
            )}
            {report.runtime.vision && (
              <Row
                leading={<Tile icon="eye" tone={report.runtime.vision.available ? "ok" : "warn"} />}
                title={`Vision (${report.runtime.vision.provider ?? "server"})`}
                description={report.runtime.vision.message || `${report.runtime.vision.model} @ ${report.runtime.vision.endpoint}`}
              >
                <Badge tone={report.runtime.vision.available ? "ok" : "warn"}>
                  {report.runtime.vision.status ?? "unknown"}
                </Badge>
              </Row>
            )}
            {report.runtime.stt && (
              <Row
                leading={<Tile icon="mic" tone={report.runtime.stt.available ? "ok" : "warn"} />}
                title="Speech-to-Text"
                description={report.runtime.stt.message || `${report.runtime.stt.primary} (fallback: ${report.runtime.stt.fallback})`}
              >
                <Badge tone={report.runtime.stt.available ? "ok" : "warn"}>
                  {report.runtime.stt.status ?? "unknown"}
                </Badge>
              </Row>
            )}
          </Section>
        )}

        <Section
          title={t("diagnostics.desktop.title")}
          description={t("diagnostics.desktop.description")}
          actions={
            unavailableCount > 0 ? (
              <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                {t("diagnostics.desktop.hideUnavailable")}
                <Switch
                  checked={hideUnavailable}
                  onCheckedChange={setHideUnavailable}
                  ariaLabel={t("diagnostics.desktop.hideUnavailable")}
                />
              </label>
            ) : undefined
          }
        >
          {report === null ? (
            <SkeletonRows count={3} />
          ) : (
            <>
              <Row
                leading={<Tile icon="monitor" tone={compositor?.detected && compositor.detected !== "unknown" ? "ok" : "warn"} />}
                title={t("diagnostics.desktop.detected")}
                description={
                  compositor?.detected && compositor.detected !== "unknown"
                    ? (compositor.evidence ?? []).join(" · ") || compositor.desktop || undefined
                    : t("diagnostics.desktop.unknownHint")
                }
              >
                <Badge tone={compositor?.detected && compositor.detected !== "unknown" ? "ok" : "warn"} dot>
                  {compositor?.detected && compositor.detected !== "unknown"
                    ? `${backendLabel(compositor.detected)}${compositor.plasma_version ? ` ${compositor.plasma_version}` : ""}`
                    : t("diagnostics.desktop.unknown")}
                </Badge>
              </Row>
              <Row
                leading={<Tile icon="window" tone={compositor?.available ? "ok" : "muted"} />}
                title={t("diagnostics.desktop.backend")}
                description={
                  <span className="font-mono text-[11.5px]">
                    {compositor?.requested && compositor.requested !== "auto"
                      ? t("diagnostics.desktop.override")
                      : compositor?.reason}
                    {compositor?.session_type ? ` · ${t("diagnostics.desktop.session")}: ${compositor.session_type}` : ""}
                  </span>
                }
              >
                <Badge tone={compositor?.available ? "accent" : "muted"}>{backendLabel(compositor?.active)}</Badge>
              </Row>
              {visibleCaps.map((name) => {
                const available = Boolean(caps[name]);
                const label = name in (CAP_KEYS as Record<string, true>)
                  ? t(`diagnostics.desktop.caps.${name as CapKey}`)
                  : name;
                return (
                  <Row
                    key={name}
                    leading={
                      <span className="flex w-7 justify-center">
                        <StatusDot tone={available ? "ok" : "muted"} />
                      </span>
                    }
                    title={label}
                    className={cn(!available && "opacity-70")}
                  >
                    <span
                      className="text-xs"
                      style={{ color: available ? "var(--muted-foreground)" : "var(--warning)" }}
                    >
                      {available ? t("diagnostics.desktop.available") : t("diagnostics.desktop.unavailable")}
                    </span>
                  </Row>
                );
              })}
            </>
          )}
        </Section>

        <Section
          title={t("diagnostics.logs.title")}
          description={t("diagnostics.logs.description")}
          actions={
            <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
              {follow && <StatusDot tone="ok" pulse />}
              {t("diagnostics.logs.follow")}
              <Switch checked={follow} onCheckedChange={setFollow} ariaLabel={t("diagnostics.logs.follow")} />
            </label>
          }
        >
          <div className="flex items-center gap-2 px-3 py-2">
            <Select
              value={unit}
              onChange={setUnit}
              ariaLabel={t("diagnostics.logs.service")}
              options={services.map((service) => ({ value: service.unit, label: t(service.labelKey) }))}
              className="w-56"
            />
            <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
              {tn("diagnostics.logs.lines", lines.length)}
            </span>
            <Button size="icon-sm" variant="ghost" aria-label={t("common.copy")} title={t("common.copy")} onClick={() => void copyLogs()}>
              <Icon name="copy" size={14} />
            </Button>
            <Button size="icon-sm" variant="ghost" aria-label={t("common.clear")} title={t("common.clear")} onClick={() => setLines([])}>
              <Icon name="trash" size={14} />
            </Button>
          </div>
          <div
            ref={viewRef}
            tabIndex={0}
            aria-label={t("diagnostics.logs.title")}
            className="focus-ring h-72 overflow-auto bg-[color-mix(in_oklab,var(--foreground)_3.5%,var(--card))] px-4 py-3"
          >
            {lines.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-xs text-muted-foreground">
                <Icon name={follow ? "activity" : "square"} size={18} className="opacity-60" />
                {follow ? t("diagnostics.logs.waiting") : t("diagnostics.logs.paused")}
              </div>
            ) : (
              <pre className="whitespace-pre font-mono text-[11px] leading-[1.7] text-foreground/85">
                {lines.map((line, index) => (
                  <LogLine key={index} text={line} />
                ))}
              </pre>
            )}
          </div>
        </Section>

        <Section title={t("diagnostics.bundle.title")} description={t("diagnostics.bundle.description")}>
          <Row leading={<Tile icon="download" tone="accent" />} title={t("diagnostics.bundle.export")} description={t("diagnostics.bundle.exportHint")}>
            <Button icon="download" loading={exporting} onClick={() => void exportBundle()}>
              {t("diagnostics.bundle.export")}
            </Button>
          </Row>
        </Section>
      </PageBody>
    </>
  );
}
