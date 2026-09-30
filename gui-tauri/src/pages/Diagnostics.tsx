import { useCallback, useEffect, useRef, useState } from "react";

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
import { useTauriEvent } from "../lib/events";
import { SERVICES } from "../lib/services";
import { cn } from "../lib/utils";
import type { DoctorReport } from "../lib/types";

const MAX_LINES = 2000;

export function DiagnosticsPage() {
  const { t, tn } = useI18n();
  const toast = useToast();
  const [unit, setUnit] = useState(SERVICES[0].unit);
  const [follow, setFollow] = useState(true);
  const [lines, setLines] = useState<string[]>([]);
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [doctorLoading, setDoctorLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
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
      .catch((error) => toast(t("diagnostics.logs.tailFailed", { error: String(error) }), "error"));
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
        return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
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
      setReport({ ok: false, connected: false, error: String(error), plugins: [] });
    } finally {
      setDoctorLoading(false);
    }
  }, []);

  useEffect(() => {
    void runDoctor();
  }, [runDoctor]);

  const exportBundle = async () => {
    setExporting(true);
    try {
      const result = await api.exportBundle();
      toast(t("diagnostics.bundle.done", { path: result.path }), "ok");
    } catch (error) {
      toast(t("diagnostics.bundle.failed", { error: String(error) }), "error");
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
                description={report.ok ? t("diagnostics.health.allGood") : report.error || t("diagnostics.health.issues")}
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
              options={SERVICES.map((service) => ({ value: service.unit, label: t(service.labelKey) }))}
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
                  <div key={index}>{line}</div>
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
