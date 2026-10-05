import { useCallback, useEffect, useMemo, useState } from "react";

import { Icon } from "../components/icons";
import { PageBody, PageHeader } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { Row, Tile } from "../components/ui/Row";
import { SkeletonRows } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/States";
import { Segmented } from "../components/ui/Tabs";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { KIND_ICON, kindLabelKey } from "../lib/appKinds";
import { splitList, titleCase } from "../lib/format";
import { cn } from "../lib/utils";
import type { AppProfile, ProfileList, ProfileOverride } from "../lib/types";

type Filter = "main" | "edited" | "all";

const ACTION_RE = /^[a-z0-9_]{1,40}$/;
const CHORD_RE = /^[A-Za-z0-9_+-]{1,40}$/;

function actionLabel(name: string): string {
  return titleCase(name.replace(/_/g, " "));
}

function launchText(launch: AppProfile["launch"]): string {
  return Array.isArray(launch) ? launch.join(" ") : String(launch ?? "");
}

function ProfileEditor({
  profile,
  onClose,
  onSaved,
}: {
  profile: AppProfile;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [aliases, setAliases] = useState(profile.aliases.join(", "));
  const [shortcuts, setShortcuts] = useState<Record<string, string>>({ ...profile.shortcuts });
  const [searchUrl, setSearchUrl] = useState(profile.search_url ?? "");
  const [newName, setNewName] = useState("");
  const [newKeys, setNewKeys] = useState("");
  const [saving, setSaving] = useState(false);

  const builtin = profile.builtin_shortcuts;
  const names = Object.keys(shortcuts).sort((a, b) => Number(!(a in builtin)) - Number(!(b in builtin)) || a.localeCompare(b));
  const invalid = Object.entries(shortcuts).some(([, chord]) => !CHORD_RE.test(chord.trim()));
  const urlInvalid = Boolean(searchUrl.trim()) && (!/^https?:\/\//.test(searchUrl.trim()) || !searchUrl.includes("{q}"));
  const canAdd = ACTION_RE.test(newName.trim()) && CHORD_RE.test(newKeys.trim()) && !(newName.trim() in shortcuts);
  const example = profile.aliases[0] ?? profile.name;

  const add = () => {
    if (!canAdd) return;
    setShortcuts((current) => ({ ...current, [newName.trim()]: newKeys.trim() }));
    setNewName("");
    setNewKeys("");
  };

  const save = async () => {
    const override: ProfileOverride = {};
    const aliasList = splitList(aliases);
    // Re-save earlier user edits too: the override file is rewritten whole.
    if (aliasList.join(",") !== profile.aliases.join(",") || profile.user?.aliases) override.aliases = aliasList;
    // Only store what differs from the built-in profile.
    const changed: Record<string, string> = {};
    for (const [name, chord] of Object.entries(shortcuts)) {
      if (builtin[name] !== chord.trim()) changed[name] = chord.trim();
    }
    if (Object.keys(changed).length) override.shortcuts = changed;
    if (searchUrl.trim() && (searchUrl.trim() !== (profile.search_url ?? "") || profile.user?.search_url)) {
      override.search_url = searchUrl.trim();
    }
    setSaving(true);
    try {
      const result = await api.appProfileSave(profile.id, override);
      if (result.ok) {
        toast(t("apps.editor.saved", { name: profile.name }), "ok");
        onSaved();
        onClose();
      } else {
        toast(t("apps.editor.saveFailed", { detail: (result.stderr || result.stdout).trim().slice(0, 160) }), "error");
      }
    } catch (error) {
      toast(t("apps.editor.saveFailed", { detail: String(error) }), "error");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    try {
      await api.appProfileReset(profile.id);
      toast(t("apps.editor.resetDone", { name: profile.name }), "ok");
      onSaved();
      onClose();
    } catch (error) {
      toast(t("apps.editor.saveFailed", { detail: String(error) }), "error");
    }
  };

  return (
    <Modal
      open
      size="lg"
      onClose={onClose}
      title={t("apps.editor.title", { name: profile.name })}
      description={t("apps.editor.description", { example })}
      footer={
        <>
          {profile.user && (
            <Button variant="ghost" icon="refresh" className="mr-auto" onClick={() => void reset()}>
              {t("apps.editor.reset")}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" loading={saving} disabled={invalid || urlInvalid} onClick={() => void save()}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <label className="block">
          <span className="text-xs font-medium text-foreground">{t("apps.editor.names")}</span>
          <Input className="mt-1.5" value={aliases} onChange={(event) => setAliases(event.target.value)} />
          <span className="mt-1 block text-[11.5px] text-muted-foreground">{t("apps.editor.namesHint")}</span>
        </label>

        <div>
          <div className="flex items-end justify-between gap-4">
            <span className="text-xs font-medium text-foreground">{t("apps.editor.actions")}</span>
            <span className="text-[11.5px] text-muted-foreground">{t("apps.editor.actionsHint")}</span>
          </div>
          <div className="mt-1.5 divide-y divide-line overflow-hidden rounded-lg shadow-[0_0_0_1px_var(--line-strong)]">
            {names.length === 0 && (
              <p className="px-3 py-3 text-xs text-muted-foreground">{t("apps.editor.noActions")}</p>
            )}
            {names.map((name) => {
              const value = shortcuts[name];
              const isNew = !(name in builtin);
              const changed = !isNew && builtin[name] !== value.trim();
              const bad = !CHORD_RE.test(value.trim());
              return (
                <div key={name} className={cn("flex items-center gap-3 px-3 py-1.5", (changed || isNew) && "bg-accent-soft")}>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-foreground">{actionLabel(name)}</div>
                    <div className="font-mono text-[10.5px] text-muted-foreground">{name}</div>
                  </div>
                  {changed && <Badge tone="accent">{t("apps.editor.changed")}</Badge>}
                  {isNew && <Badge tone="accent">{t("apps.editor.added")}</Badge>}
                  <Input
                    value={value}
                    aria-label={`${actionLabel(name)} — ${t("apps.editor.keys")}`}
                    aria-invalid={bad || undefined}
                    onChange={(event) => setShortcuts((current) => ({ ...current, [name]: event.target.value }))}
                    className={cn("w-40 font-mono text-[12px]", bad && "shadow-[inset_0_0_0_1px_var(--destructive)]")}
                  />
                  {isNew ? (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t("apps.editor.remove", { name: actionLabel(name) })}
                      onClick={() =>
                        setShortcuts((current) => {
                          const next = { ...current };
                          delete next[name];
                          return next;
                        })
                      }
                    >
                      <Icon name="x" size={14} />
                    </Button>
                  ) : changed ? (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      title={builtin[name]}
                      aria-label={t("apps.editor.reset")}
                      onClick={() => setShortcuts((current) => ({ ...current, [name]: builtin[name] }))}
                    >
                      <Icon name="refresh" size={13} />
                    </Button>
                  ) : (
                    <span className="w-7" />
                  )}
                </div>
              );
            })}
            <div className="flex items-center gap-2 bg-wash px-3 py-2">
              <Input
                value={newName}
                placeholder={t("apps.editor.newName")}
                aria-label={t("apps.editor.action")}
                onChange={(event) => setNewName(event.target.value.toLowerCase().replace(/\s+/g, "_"))}
                onKeyDown={(event) => event.key === "Enter" && add()}
                className="flex-1 font-mono text-[12px]"
              />
              <Input
                value={newKeys}
                placeholder={t("apps.editor.newKeys")}
                aria-label={t("apps.editor.keys")}
                onChange={(event) => setNewKeys(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && add()}
                className="w-40 font-mono text-[12px]"
              />
              <Button size="sm" icon="check" disabled={!canAdd} onClick={add}>
                {t("apps.editor.add")}
              </Button>
            </div>
          </div>
        </div>

        <label className="block">
          <span className="text-xs font-medium text-foreground">{t("apps.editor.searchUrl")}</span>
          <Input
            className={cn("mt-1.5 font-mono text-[12px]", urlInvalid && "shadow-[inset_0_0_0_1px_var(--destructive)]")}
            value={searchUrl}
            placeholder="https://example.com/search?q={q}"
            onChange={(event) => setSearchUrl(event.target.value)}
          />
          <span className="mt-1 block text-[11.5px] text-muted-foreground">{t("apps.editor.searchUrlHint")}</span>
        </label>

        {launchText(profile.launch) && (
          <div>
            <span className="text-xs font-medium text-foreground">{t("apps.editor.launch")}</span>
            <code className="mt-1.5 block truncate rounded-md bg-wash px-2.5 py-2 font-mono text-[11.5px] text-muted-foreground">
              {launchText(profile.launch)}
            </code>
          </div>
        )}
      </div>
    </Modal>
  );
}

export function AppsPage() {
  const { t, tn } = useI18n();
  const [data, setData] = useState<ProfileList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("main");
  const [editing, setEditing] = useState<AppProfile | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.appProfilesList());
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Dev-only screenshot affordance: UTTER_GUI_ROUTE="apps?edit=<id>".
  useEffect(() => {
    if (!import.meta.env.DEV || !data) return;
    const id = new URLSearchParams(sessionStorage.getItem("utter.dev.query") ?? "").get("edit");
    const match = id && data.profiles.find((profile) => profile.id === id);
    if (match) setEditing(match);
    sessionStorage.removeItem("utter.dev.query");
  }, [data]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data?.profiles ?? [])
      .filter((profile) => !profile.id.startsWith("generic-"))
      // "Main apps" = the common ones Utter ships plus your own; "All" adds
      // every app installed on this computer.
      .filter((profile) => (filter === "edited" ? profile.user : filter === "main" ? profile.curated || profile.user : true))
      .filter(
        (profile) =>
          !needle ||
          profile.name.toLowerCase().includes(needle) ||
          profile.id.toLowerCase().includes(needle) ||
          profile.aliases.some((alias) => alias.toLowerCase().includes(needle)),
      )
      .sort(
        (a, b) =>
          Number(!a.user) - Number(!b.user) ||
          Number(!a.curated) - Number(!b.curated) ||
          a.name.localeCompare(b.name),
      );
  }, [data, query, filter]);

  const kindLabel = (kind: string) => t(kindLabelKey(kind));

  return (
    <>
      <PageHeader title={t("apps.title")} description={t("apps.description")} />
      <PageBody>
        {data && !data.loader_reads_user && data.profiles.some((profile) => profile.user) && (
          <div className="flex items-start gap-3 rounded-lg bg-[color-mix(in_oklab,var(--warning)_10%,var(--card))] px-4 py-3.5 shadow-[0_0_0_1px_color-mix(in_oklab,var(--warning)_30%,transparent)]">
            <Icon name="info" size={16} className="mt-0.5 shrink-0 text-[color:var(--warning)]" />
            <div>
              <div className="text-[13px] font-medium text-foreground">{t("apps.pendingTitle")}</div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("apps.pendingBody", { path: data.user_dir.replace(/^\/home\/[^/]+/, "~") })}
              </p>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[14rem] flex-1">
            <Icon
              name="search"
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={query}
              type="search"
              placeholder={t("apps.search")}
              aria-label={t("apps.search")}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-8"
            />
          </div>
          <Segmented<Filter>
            ariaLabel={t("apps.search")}
            value={filter}
            onChange={setFilter}
            options={[
              { value: "main", label: t("apps.filters.curated") },
              { value: "edited", label: t("apps.filters.edited") },
              { value: "all", label: t("apps.filters.all") },
            ]}
          />
        </div>

        <Section
          title={data ? tn("apps.listTitle", visible.length) : t("common.loading")}
          description={t("apps.listDescription")}
        >
          {error ? (
            <ErrorState title={t("apps.loadError")} message={error} onRetry={() => void load()} />
          ) : data === null ? (
            <SkeletonRows count={6} />
          ) : visible.length === 0 ? (
            <EmptyState
              icon="search"
              title={t("apps.emptyTitle")}
              description={t("apps.emptyBody")}
              compact
              action={
                (query || filter !== "main") && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setQuery("");
                      setFilter("main");
                    }}
                  >
                    {t("common.clear")}
                  </Button>
                )
              }
            />
          ) : (
            visible.map((profile) => {
              const count = Object.keys(profile.shortcuts).length;
              const preview = Object.entries(profile.shortcuts).slice(0, 3);
              return (
                <Row
                  key={profile.id}
                  as="button"
                  onClick={() => setEditing(profile)}
                  leading={<Tile icon={KIND_ICON[profile.kind] ?? "window"} tone={profile.curated ? "accent" : "muted"} />}
                  title={
                    <span className="flex items-center gap-2">
                      <span className="truncate">{profile.name}</span>
                      {profile.own ? (
                        <Badge tone="neutral">{t("apps.yours")}</Badge>
                      ) : (
                        profile.user && <Badge tone="accent">{t("apps.edited")}</Badge>
                      )}
                    </span>
                  }
                  description={`${kindLabel(profile.kind)} · ${tn("apps.actions", count)}`}
                >
                  <span className="hidden items-center gap-1 md:flex">
                    {preview.map(([name, chord]) => (
                      <span key={name} className="kbd" title={actionLabel(name)}>
                        {chord}
                      </span>
                    ))}
                  </span>
                  <Icon name="chevron-right" size={15} className="text-muted-foreground" />
                </Row>
              );
            })
          )}
        </Section>
      </PageBody>
      {editing && <ProfileEditor profile={editing} onClose={() => setEditing(null)} onSaved={() => void load()} />}
    </>
  );
}
