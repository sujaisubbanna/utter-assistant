import { useCallback, useEffect, useState } from "react";

import { Icon } from "../components/icons";
import { PageBody, PageHeader } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button, LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Modal } from "../components/ui/Modal";
import { Row, Tile, Value } from "../components/ui/Row";
import { SkeletonRows } from "../components/ui/Skeleton";
import { StatusDot } from "../components/ui/StatusDot";
import { EmptyState } from "../components/ui/States";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { useI18n, type MessageKey } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { titleCase } from "../lib/format";
import { DEP_HELP } from "../lib/links";
import { cn } from "../lib/utils";
import type { DoctorReport, Plugin } from "../lib/types";

const OK_STATES = new Set(["running", "ready", "active", "ok", "loaded", "negotiated"]);
const BAD_STATES = new Set(["failed", "error", "crashed"]);

function toneFor(status?: string): "ok" | "error" | "muted" {
  const value = (status ?? "").toLowerCase();
  if (OK_STATES.has(value)) return "ok";
  if (BAD_STATES.has(value)) return "error";
  return "muted";
}

function PermissionDialog({ plugin, onClose }: { plugin: Plugin; onClose: () => void }) {
  const { t } = useI18n();
  const permissions = plugin.permissions ?? [];
  return (
    <Modal
      open
      onClose={onClose}
      title={t("plugins.permissions.title", { name: String(plugin.id) })}
      description={t("plugins.permissions.description")}
    >
      <div className="divide-y divide-line overflow-hidden rounded-lg shadow-[0_0_0_1px_var(--line)]">
        {permissions.length === 0 && (
          <p className="px-3.5 py-3 text-[13px] text-muted-foreground">{t("plugins.permissions.none")}</p>
        )}
        {permissions.map((permission, index) => (
          <div key={index} className="flex items-center justify-between gap-4 px-3.5 py-2.5">
            <span className="text-[13px]">{titleCase(String(permission.name ?? "?").replace(/\./g, " "))}</span>
            <Badge tone={permission.enforced ? "ok" : "warn"}>
              {permission.enforced ? t("plugins.permissions.enforced") : t("plugins.permissions.advisory")}
            </Badge>
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-1.5">
        {(plugin.unknown_capabilities ?? []).map((cap) => (
          <div key={cap} className="flex items-center gap-2 text-[13px] text-[color:var(--warning)]">
            <Icon name="alert" size={14} />
            {t("plugins.permissions.unknownCap", { name: cap })}
          </div>
        ))}
        {(plugin.missing_requires ?? []).map((req) => (
          <div key={req} className="flex items-center gap-2 text-[13px] text-[color:var(--destructive)]">
            <Icon name="alert" size={14} />
            {t("plugins.permissions.missingReq", { name: req })}
          </div>
        ))}
      </div>
    </Modal>
  );
}

function PluginEntry({ plugin }: { plugin: Plugin }) {
  const { t, tn } = useI18n();
  const { get, set } = useConfig();
  const toast = useToast();
  const [expanded, setExpanded] = useState(false);
  const [permissions, setPermissions] = useState(false);

  const name = String(plugin.id);
  const disabled = get<string[]>("plugins", "disabled", []);
  const enabled = !disabled.includes(name);

  const toggle = (next: boolean) => {
    const list = next ? disabled.filter((item) => item !== name) : [...disabled, name];
    void set("plugins", "disabled", list);
    toast(t(next ? "plugins.list.enabledToast" : "plugins.list.disabledToast", { name }), next ? "ok" : "warn");
  };

  const negotiated = plugin.negotiated ?? {};
  const detailId = `plugin-${name.replace(/\W+/g, "-")}`;

  return (
    <div>
      <div className="flex min-h-[52px] items-center gap-3 px-4 py-2.5">
        <Tile icon="puzzle" tone={toneFor(plugin.status) === "error" ? "danger" : "accent"} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] font-medium text-foreground">{name}</span>
            <StatusDot tone={toneFor(plugin.status)} />
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {plugin.kind} · {plugin.status ?? t("common.unknown")}
          </div>
        </div>
        {(plugin.unknown_capabilities?.length ?? 0) > 0 && <Badge tone="warn">{t("plugins.list.unknownCap")}</Badge>}
        {(plugin.missing_requires?.length ?? 0) > 0 && <Badge tone="danger">{t("plugins.list.missingReq")}</Badge>}
        <Switch checked={enabled} onCheckedChange={toggle} ariaLabel={t("plugins.list.toggle", { name })} />
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={expanded ? t("plugins.list.collapse") : t("plugins.list.expand")}
          aria-expanded={expanded}
          aria-controls={detailId}
          onClick={() => setExpanded((value) => !value)}
        >
          <Icon
            name="chevron-down"
            size={15}
            className={cn("transition-transform duration-150 ease-out", expanded && "rotate-180")}
          />
        </Button>
      </div>
      {expanded && (
        <div id={detailId} className="animate-fade-up border-t border-line bg-wash px-4 py-3.5 text-xs">
          <dl className="grid grid-cols-[7rem_1fr] gap-x-4 gap-y-2">
            <dt className="text-muted-foreground">{t("plugins.list.kind")}</dt>
            <dd className="font-mono text-[11.5px]">{plugin.kind ?? "?"} · epoch {plugin.epoch ?? "?"}</dd>
            <dt className="text-muted-foreground">{t("plugins.list.negotiated")}</dt>
            <dd className="font-mono text-[11.5px]">
              {negotiated.protocol ?? "?"} · abi {negotiated.abi ?? "?"}
            </dd>
            {plugin.provides && plugin.provides.length > 0 && (
              <>
                <dt className="text-muted-foreground">{t("plugins.list.provides")}</dt>
                <dd className="flex flex-wrap gap-1">
                  {plugin.provides.map((cap) => (
                    <Badge key={cap} tone="muted" className="font-mono">
                      {cap}
                    </Badge>
                  ))}
                </dd>
              </>
            )}
            {plugin.requires && plugin.requires.length > 0 && (
              <>
                <dt className="text-muted-foreground">{t("plugins.list.requires")}</dt>
                <dd className="flex flex-wrap gap-1">
                  {plugin.requires.map((cap) => (
                    <Badge key={cap} tone="muted" className="font-mono">
                      {cap}
                    </Badge>
                  ))}
                </dd>
              </>
            )}
            {plugin.error && (
              <>
                <dt className="text-muted-foreground">{t("plugins.list.error")}</dt>
                <dd className="text-[color:var(--destructive)]">{plugin.error}</dd>
              </>
            )}
          </dl>
          <Button size="sm" icon="lock" className="mt-3" onClick={() => setPermissions(true)}>
            {tn("plugins.list.permissions", (plugin.permissions ?? []).length)}
          </Button>
        </div>
      )}
      {permissions && <PermissionDialog plugin={plugin} onClose={() => setPermissions(false)} />}
    </div>
  );
}

export function PluginsPage() {
  const { t, tn } = useI18n();
  const toast = useToast();
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await api.doctor());
    } catch (error) {
      setReport({ ok: false, connected: false, error: String(error), plugins: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  const restart = async () => {
    setRestarting(true);
    try {
      const result = await api.systemctl("restart", "utter-runner");
      toast(
        result.ok ? t("plugins.restarted") : t("plugins.restartFailed", { detail: (result.stderr || "").slice(0, 120) }),
        result.ok ? "ok" : "error",
      );
      window.setTimeout(() => void run(), 800);
    } finally {
      setRestarting(false);
    }
  };

  const copyFix = async (fix: string) => {
    try {
      await navigator.clipboard.writeText(fix);
      toast(t("plugins.deps.fixCopied"), "ok");
    } catch {
      toast(t("diagnostics.logs.copyFailed"), "error");
    }
  };

  const connected = Boolean(report?.connected);
  const runner = report?.runner ?? {};
  const deps = report?.deps ?? {};
  // Missing tools first, so the things to fix are at the top.
  const depNames = Object.keys(deps).sort((a, b) => Number(deps[a]) - Number(deps[b]) || a.localeCompare(b));

  return (
    <>
      <PageHeader
        title={t("plugins.title")}
        description={t("plugins.description")}
        actions={
          <>
            <Button variant="ghost" icon="refresh" loading={loading} onClick={() => void run()}>
              {t("plugins.check")}
            </Button>
            <Button icon="power" loading={restarting} onClick={() => void restart()}>
              {t("plugins.restart")}
            </Button>
          </>
        }
      />
      <PageBody>
        <Section title={t("plugins.list.title")} description={t("plugins.list.description")}>
          {report === null ? (
            <SkeletonRows count={2} />
          ) : !connected ? (
            <EmptyState
              icon="power"
              title={t("plugins.list.offlineTitle")}
              description={report.error || t("plugins.list.offlineBody")}
              action={
                <Button icon="refresh" onClick={() => void run()}>
                  {t("common.retry")}
                </Button>
              }
            />
          ) : (report.plugins ?? []).length === 0 ? (
            <EmptyState icon="puzzle" title={t("plugins.list.emptyTitle")} description={t("plugins.list.emptyBody")} />
          ) : (
            (report.plugins ?? []).map((plugin) => <PluginEntry key={plugin.id} plugin={plugin} />)
          )}
        </Section>

        <Section title={t("plugins.deps.title")} description={t("plugins.deps.description")}>
          {report === null ? (
            <SkeletonRows count={4} />
          ) : depNames.length === 0 ? (
            <EmptyState icon="grid" title={t("plugins.deps.emptyTitle")} description={t("plugins.deps.emptyBody")} compact />
          ) : (
            depNames.map((name) => {
              const ok = deps[name];
              const help = DEP_HELP[name];
              const label = name in DEP_HELP ? t(`deps.${name}` as MessageKey) : titleCase(name);
              return (
                <Row
                  key={name}
                  leading={
                    <span className="flex w-7 justify-center">
                      <StatusDot tone={ok ? "ok" : "error"} />
                    </span>
                  }
                  title={label}
                  description={!ok && help?.fix ? <code className="font-mono text-[11.5px]">{help.fix}</code> : undefined}
                >
                  {!ok && help?.fix && (
                    <Button size="sm" variant="ghost" icon="copy" onClick={() => void copyFix(help.fix!)}>
                      {t("plugins.deps.fix")}
                    </Button>
                  )}
                  {!ok && help?.url && <LinkButton href={help.url}>{t("common.install")}</LinkButton>}
                  <span
                    className="text-xs"
                    style={{ color: ok ? "var(--muted-foreground)" : "var(--destructive)" }}
                  >
                    {ok ? t("plugins.deps.ok") : t("plugins.deps.missing")}
                  </span>
                </Row>
              );
            })
          )}
        </Section>

        <Section title={t("plugins.runner.title")} description={t("plugins.runner.description")}>
          <Row leading={<Tile icon="cpu" />} title={t("plugins.runner.version")} description={report?.error || undefined}>
            <Value>{runner.version ?? "—"}</Value>
          </Row>
          <Row leading={<Tile icon="link" />} title={t("plugins.runner.protocol")}>
            <Value>
              {runner.protocol ?? "?"} · abi {runner.abi ?? "?"}
            </Value>
          </Row>
          <Row leading={<Tile icon="activity" />} title={t("plugins.runner.health")}>
            {report === null ? (
              <Badge tone="neutral">{t("common.loading")}</Badge>
            ) : (
              <Badge tone={report.ok ? "ok" : "warn"} dot>
                {report.ok ? t("plugins.runner.healthy") : t("plugins.runner.issues")}
              </Badge>
            )}
          </Row>
          {(report?.drift?.length ?? 0) > 0 && (
            <Row
              leading={<Tile icon="alert" tone="warn" />}
              title={t("plugins.runner.drift")}
              description={<span className="font-mono text-[11.5px]">{JSON.stringify(report?.drift)}</span>}
            >
              <Badge tone="warn">{tn("plugins.runner.driftItems", report?.drift?.length ?? 0)}</Badge>
            </Row>
          )}
        </Section>
      </PageBody>
    </>
  );
}
