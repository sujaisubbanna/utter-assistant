import type { IconName } from "../components/icons";
import type { MessageKey } from "../i18n";

export interface NavItem {
  id: string;
  labelKey: MessageKey;
  icon: IconName;
}

export interface NavGroup {
  labelKey: MessageKey;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    labelKey: "nav.groups.essentials",
    items: [
      { id: "general", labelKey: "nav.general", icon: "sliders" },
      { id: "voice", labelKey: "nav.voice", icon: "mic" },
      { id: "models", labelKey: "nav.models", icon: "box" },
    ],
  },
  {
    labelKey: "nav.groups.understanding",
    items: [
      { id: "apps", labelKey: "nav.apps", icon: "grid" },
      { id: "llm", labelKey: "nav.llm", icon: "sparkles" },
      { id: "tts", labelKey: "nav.tts", icon: "volume" },
      { id: "perception", labelKey: "nav.perception", icon: "eye" },
    ],
  },
  {
    labelKey: "nav.groups.advanced",
    items: [
      { id: "plugins", labelKey: "nav.plugins", icon: "puzzle" },
      { id: "safety", labelKey: "nav.safety", icon: "shield" },
      { id: "diagnostics", labelKey: "nav.diagnostics", icon: "lifebuoy" },
    ],
  },
];

export const NAV_IDS = NAV.flatMap((group) => group.items.map((item) => item.id));

export function navItem(id: string): NavItem | undefined {
  for (const group of NAV) {
    const found = group.items.find((item) => item.id === id);
    if (found) return found;
  }
  return undefined;
}

export function navLabelKey(id: string): MessageKey {
  if (id === "about") return "nav.about";
  return navItem(id)?.labelKey ?? "app.settings";
}
