import type { ComponentType } from "react";

import { AboutPage } from "./About";
import { AppsPage } from "./Apps";
import { DiagnosticsPage } from "./Diagnostics";
import { GeneralPage } from "./General";
import { LlmPage } from "./Llm";
import { ModelsPage } from "./Models";
import { PerceptionPage } from "./Perception";
import { PluginsPage } from "./Plugins";
import { SafetyPage } from "./Safety";
import { TtsPage } from "./Tts";
import { VoicePage } from "./Voice";

export const PAGES: Record<string, ComponentType> = {
  general: GeneralPage,
  voice: VoicePage,
  models: ModelsPage,
  apps: AppsPage,
  llm: LlmPage,
  tts: TtsPage,
  perception: PerceptionPage,
  plugins: PluginsPage,
  safety: SafetyPage,
  diagnostics: DiagnosticsPage,
  about: AboutPage,
};

export function isPageId(id: string): boolean {
  return id in PAGES;
}
