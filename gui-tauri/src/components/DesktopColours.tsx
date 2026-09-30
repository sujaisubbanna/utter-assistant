import { useT } from "../i18n";
import { modeIsDark, useTheme } from "../lib/theme";
import { Row, Tile } from "./ui/Row";
import { Switch } from "./ui/Switch";

/** Opt-in: let a matugen palette replace the default grey + yellow. */
export function DesktopColoursRow() {
  const t = useT();
  const { mode, palette, desktopColours, setDesktopColours } = useTheme();
  const available = Boolean(palette?.available && palette.dark === modeIsDark(mode));
  return (
    <Row
      leading={<Tile icon="palette" tone={desktopColours && available ? "accent" : "muted"} />}
      title={t("theme.desktop")}
      description={available || !palette ? t("theme.desktopHint") : t("theme.desktopMissing")}
    >
      <Switch checked={desktopColours} onCheckedChange={setDesktopColours} ariaLabel={t("theme.desktop")} />
    </Row>
  );
}
