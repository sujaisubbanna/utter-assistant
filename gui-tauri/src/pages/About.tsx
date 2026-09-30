import { useEffect, useState } from "react";

import { LogoTile } from "../components/Logo";
import { PrivacyCard } from "../components/Privacy";
import { PageBody, PageHeader } from "../components/PageHeader";
import { ThemeControl } from "../components/ThemeControl";
import { LanguageSelect } from "../components/LanguageSelect";
import { DesktopColoursRow } from "../components/DesktopColours";
import { Badge } from "../components/ui/Badge";
import { LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Row, Tile, Value } from "../components/ui/Row";
import { Skeleton } from "../components/ui/Skeleton";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { PROJECT_URL } from "../lib/links";
import { useTheme } from "../lib/theme";
import type { AppInfo } from "../lib/types";

export function AboutPage() {
  const t = useT();
  const [info, setInfo] = useState<AppInfo | null>(null);
  const { paletteActive, palette } = useTheme();

  useEffect(() => {
    api.appInfo().then(setInfo).catch(() => {});
  }, []);

  const path = (value?: string) => (info ? <Value>{value || "—"}</Value> : <Skeleton className="h-3 w-48" />);

  return (
    <>
      <PageHeader title={t("about.title")} description={t("about.description")} />
      <PageBody>
        <section className="relative overflow-hidden rounded-lg bg-card shadow-card">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 -top-32 mx-auto h-64 w-[36rem] rounded-full blur-3xl"
            style={{ background: "radial-gradient(closest-side, var(--accent-soft), transparent)" }}
          />
          <div className="relative flex flex-col items-center gap-4 px-6 pb-8 pt-10 text-center">
            <LogoTile size={64} />
            <div>
              <div className="font-display text-[28px] font-semibold lowercase tracking-[-0.02em] text-foreground">{t("app.name")}</div>
              <p className="mt-1 text-[13px] text-muted-foreground">{t("about.tagline")}</p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-1.5">
              <Badge tone="accent">v{info?.version ?? "0.1.0"}</Badge>
              <Badge tone="muted">Tauri {info?.tauri ?? "2"}</Badge>
              <Badge tone="muted">protocol {info?.protocol ?? "1.0"}</Badge>
            </div>
            {PROJECT_URL && (
              <LinkButton href={PROJECT_URL} variant="secondary" size="md">
                {t("about.credits.project")}
              </LinkButton>
            )}
          </div>
        </section>

        <PrivacyCard />

        <Section title={t("about.runtime.title")} description={t("about.runtime.description")}>
          <Row leading={<Tile icon="folder" />} title={t("about.runtime.repo")}>{path(info?.repo)}</Row>
          <Row leading={<Tile icon="terminal" />} title={t("about.runtime.python")}>{path(info?.python)}</Row>
          <Row leading={<Tile icon="sliders" />} title={t("about.runtime.config")}>{path(info?.config_path)}</Row>
          <Row leading={<Tile icon="link" />} title={t("about.runtime.socket")}>{path(info?.runner_sock)}</Row>
        </Section>

        <Section title={t("about.appearance.title")}>
          <Row leading={<Tile icon="sun" />} title={t("theme.label")}>
            <ThemeControl />
          </Row>
          <Row leading={<Tile icon="globe" />} title={t("language.label")}>
            <LanguageSelect className="w-52" />
          </Row>
          <DesktopColoursRow />
          <Row
            leading={<Tile icon="palette" tone={paletteActive ? "accent" : "muted"} />}
            title={t("about.appearance.palette")}
            description={palette?.source || "~/.local/share/utter/colors.css"}
          >
            <Badge tone={paletteActive ? "ok" : "muted"} dot={paletteActive}>
              {paletteActive
                ? t("about.appearance.paletteActive")
                : palette?.available
                  ? t("about.appearance.paletteMismatch")
                  : t("about.appearance.paletteBuiltIn")}
            </Badge>
          </Row>
        </Section>

        <Section title={t("about.credits.title")}>
          <Row title={t("about.credits.stack")}>
            <Value mono={false}>Tauri v2 · React · Tailwind CSS v4 · Inter</Value>
          </Row>
          <Row title={t("about.credits.licence")}>
            <Value mono={false}>Apache-2.0</Value>
          </Row>
        </Section>
      </PageBody>
    </>
  );
}
