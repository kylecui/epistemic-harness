/**
 * model-route-status — show the model that actually answered.
 *
 * The gateway can serve a request with a different model than the client asked for: the tier
 * chain picks another candidate on failover. It reports the truth in X-Harness-Selected-Model,
 * so this extension puts that in the footer whenever it differs from the model that was sent,
 * and clears it when they agree or when a response carries no routing headers at all (a stale
 * warning is worse than none). Read-only observer: it never touches the request.
 * Reviewed by critic 2026-11-24: string compare on headers, clear on missing headers, compare
 * against the request body's model rather than pi's model id (which may be prefixed/aliased).
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const KEY = "route";
const norm = (v: unknown) => String(v ?? "").trim().toLowerCase();

export default function (pi: ExtensionAPI) {
  let sent = "";
  let announced = "";
  let announcedQuota = "";

  pi.on("before_provider_request", async (event: any) => {
    const model = (event?.payload as any)?.model;
    if (typeof model === "string" && model.trim()) sent = model.trim();
  });

  pi.on("after_provider_response", async (event: any, ctx: any) => {
    const h = event?.headers || {};
    const get = (name: string) => String(h[name] ?? h[name.toUpperCase()] ?? "");
    const clear = () => {
      if (announced) ctx.ui?.setStatus?.(KEY, "");
      announced = "";
      if (announcedQuota) ctx.ui?.setStatus?.("quota", "");
      announcedQuota = "";
    };

    // A plan overrun is informational here: the gateway keeps routing, the operator decides whether to
    // top up or hold the model. Shown once per distinct text, cleared when the gateway stops reporting it.
    const alert = get("x-harness-quota-alert").trim();
    if (alert) {
      const text = `⚠ ${alert}`;
      ctx.ui?.setStatus?.("quota", text);
      if (text !== announcedQuota) {
        ctx.ui?.notify?.(`[router] ${alert}`, "warning");
        announcedQuota = text;
      }
    } else if (announcedQuota) {
      ctx.ui?.setStatus?.("quota", "");
      announcedQuota = "";
    }

    const unavailable = norm(get("x-harness-all-upstreams-unavailable"));
    const selected = get("x-harness-selected-model").trim();
    if (!selected) { clear(); return; }  // not our gateway, or headers abstracted away
    if (unavailable === "1" || unavailable === "true") {
      ctx.ui?.setStatus?.(KEY, "⚠ no upstream (503)");
      announced = "503";
      return;
    }
    const requested = sent || String(ctx?.model?.id || "").trim();
    if (requested && norm(selected) !== norm(requested)) {
      const text = `⚠ served by ${selected}`;
      ctx.ui?.setStatus?.(KEY, text);
      if (text !== announced) {
        ctx.ui?.notify?.(`[router] asked ${requested}, answered by ${selected}`, "warning");
        announced = text;
      }
      return;
    }
    clear();
  });
}
