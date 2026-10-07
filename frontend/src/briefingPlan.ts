import { isNative } from "./api";

const KEY = "unic.briefing";
const ID = 4200;
export const AUTO_KEY = "unic.autosend";

export function getBriefingTime(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

/** Notification quotidienne locale. Touchée : l'appli s'ouvre et lance le briefing. */
export async function scheduleBriefing(time: string | null): Promise<string> {
  try { if (time) localStorage.setItem(KEY, time); else localStorage.removeItem(KEY); } catch { /* ignoré */ }
  if (!isNative) return time ? "Enregistré. Les notifications fonctionnent dans l'appli Android." : "Briefing désactivé.";
  const { LocalNotifications } = await import("@capacitor/local-notifications");
  await LocalNotifications.cancel({ notifications: [{ id: ID }] }).catch(() => {});
  if (!time) return "Briefing quotidien désactivé.";
  const perm = await LocalNotifications.requestPermissions();
  if (perm.display !== "granted") return "Notifications refusées : autorise-les dans Réglages › Applis › UniC AI.";
  const [hour, minute] = time.split(":").map(Number);
  await LocalNotifications.schedule({
    notifications: [{
      id: ID, title: "Briefing du jour", body: "Touche pour voir devis, mails et fiche Google.",
      schedule: { on: { hour, minute }, allowWhileIdle: true }, extra: { action: "briefing" },
    }],
  });
  return `Briefing programmé chaque jour à ${time.replace(":", " h ")}.`;
}

/** À appeler une fois : ouvre la conversation et lance le briefing quand la notification est touchée. */
export async function listenBriefingTap(open: () => void): Promise<() => void> {
  if (!isNative) return () => {};
  const { LocalNotifications } = await import("@capacitor/local-notifications");
  const h = await LocalNotifications.addListener("localNotificationActionPerformed", (e) => {
    if (e.notification.extra?.action !== "briefing") return;
    try { sessionStorage.setItem(AUTO_KEY, "briefing"); } catch { /* ignoré */ }
    open();
  });
  return () => { h.remove(); };
}
