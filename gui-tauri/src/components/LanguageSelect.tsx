import { LANG_NAMES, LANGS, detectLang, useI18n, type LangPref } from "../i18n";
import { Select } from "./ui/Select";

export function LanguageSelect({ className }: { className?: string }) {
  const { pref, setPref, t } = useI18n();
  return (
    <Select
      className={className}
      ariaLabel={t("language.label")}
      value={pref}
      onChange={(next) => setPref(next as LangPref)}
      options={[
        { value: "system", label: t("language.system", { name: LANG_NAMES[detectLang()] }) },
        ...LANGS.map((lang) => ({ value: lang, label: LANG_NAMES[lang] })),
      ]}
    />
  );
}
