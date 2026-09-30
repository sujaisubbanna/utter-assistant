import { useT } from "../i18n";
import { useTheme } from "../lib/theme";
import type { ThemeMode } from "../lib/types";
import { Segmented } from "./ui/Tabs";

export function ThemeControl({
  className,
  compact,
  stretch,
}: {
  className?: string;
  compact?: boolean;
  stretch?: boolean;
}) {
  const t = useT();
  const { mode, setMode } = useTheme();
  return (
    <Segmented<ThemeMode>
      className={className}
      ariaLabel={t("theme.label")}
      size="sm"
      stretch={stretch}
      value={mode}
      onChange={setMode}
      options={[
        { value: "light", label: t("theme.light"), icon: "sun", iconOnly: compact },
        { value: "dark", label: t("theme.dark"), icon: "moon", iconOnly: compact },
        { value: "system", label: t("theme.system"), icon: "monitor", iconOnly: compact },
      ]}
    />
  );
}
