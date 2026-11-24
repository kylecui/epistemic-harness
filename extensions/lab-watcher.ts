/**
 * lab-watcher — wake the agent when a detached lab campaign finishes.
 *
 * The agent runtime has no background tick between turns; this extension is
 * the sanctioned bridge: a host-side interval polls experiments/campaign.status
 * (written by experiments/watch_campaign.ps1) and delivers ONE followUp
 * message on completion, so the analysis phase starts without human polling.
 *
 * Scope discipline: it only reads a status file and sends a message. It never
 * touches the working gateway, MCP, or settings.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const POLL_MS = 60_000;

export default function (pi: ExtensionAPI) {
  let notified = false;
  const timer = setInterval(() => {
    if (notified) {
      clearInterval(timer);
      return;
    }
    const statusPath = join(process.cwd(), "experiments", "campaign.status");
    if (!existsSync(statusPath)) return;
    let text = "";
    try {
      text = readFileSync(statusPath, "utf-8");
    } catch {
      return;
    }
    if (/^done /m.test(text)) {
      notified = true;
      clearInterval(timer);
      const line = text.split(/\r?\n/).find((l) => l.startsWith("done ")) || "done";
      pi.sendUserMessage(
        `[lab-watcher] ${line}\nCampaign finished — proceed with aggregation, analysis, and the writing tasks per the plan.`,
        { deliverAs: "followUp" },
      );
    }
  }, POLL_MS);
}
