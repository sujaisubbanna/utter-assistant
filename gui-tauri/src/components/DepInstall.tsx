import { useState } from "react";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { humanizeError } from "../lib/errors";
import { depFix, openLink } from "../lib/links";
import { usePlatform } from "../lib/platform";
import { Icon } from "./icons";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";
import { useToast } from "./ui/Toast";

/**
 * Installs a missing system tool by opening its known fix command in the user's
 * terminal — the same consent-first pattern as the engine installer (the
 * command is shown, then run by the user, never silently). Renders nothing when
 * the platform has no safe automatic fix for `dep`.
 */
export function DepInstallButton({
  dep,
  title,
  href,
  size = "sm",
}: {
  dep: string;
  title: string;
  href?: string;
  size?: "sm" | "md";
}) {
  const { t } = useI18n();
  const { os } = usePlatform();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const command = depFix(dep, os);
  if (!command) return null;

  const run = async () => {
    setOpening(true);
    try {
      await api.openDepFix(dep);
      toast(t("plugins.deps.opened"), "ok");
      setOpen(false);
    } catch (error) {
      toast(t("engine.missing.openFailed", { error: humanizeError(error, t) }), "error");
    } finally {
      setOpening(false);
    }
  };

  return (
    <>
      <Button size={size} variant="primary" icon="terminal" onClick={() => setOpen(true)}>
        {t("plugins.deps.install")}
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("plugins.deps.confirmTitle", { name: title })}
        description={t("plugins.deps.confirmBody")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            {href && (
              <Button variant="secondary" iconRight="external" onClick={() => openLink(href)}>
                {t("common.website")}
              </Button>
            )}
            <Button variant="primary" icon="terminal" loading={opening} onClick={() => void run()}>
              {t("plugins.deps.run")}
            </Button>
          </>
        }
      >
        <div className="flex items-start gap-3 rounded-lg bg-wash px-3.5 py-3 shadow-[inset_0_0_0_1px_var(--line)]">
          <Icon name="terminal" size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
          <code className="min-w-0 flex-1 select-all break-all font-mono text-[12px] text-foreground">
            {command}
          </code>
        </div>
      </Modal>
    </>
  );
}
