import { registerPlugin } from "@capacitor/core";
import type { Contact } from "./phoneMatch";
import type { Notif } from "./notifs";

/** État de « Hey UniC » (mot d'appel) : off | loading | listening | busy | missing | error. */
export type WakeInfo = { enabled: boolean; state: string; modelBundled: boolean; overlay: boolean; battery: boolean; mic: boolean };

/** Pont vers le code Android (UnicPhonePlugin.java) : contacts, appel, SMS. Absent sur le web. */
const Native = registerPlugin<{
  listContacts(): Promise<{ contacts: Contact[] }>;
  call(o: { number: string }): Promise<{ dialedOnly?: boolean } | void>;
  sendSms(o: { number: string; text: string; composer?: boolean }): Promise<{ composerOnly?: boolean } | void>;
  notificationAccess(): Promise<{ enabled: boolean }>;
  openNotificationSettings(): Promise<void>;
  listNotifications(): Promise<{ notifications: Notif[] }>;
  isLocked(): Promise<{ locked: boolean }>;
  setLockScreenMode(o: { on: boolean }): Promise<void>;
  wakeStatus(): Promise<WakeInfo>;
  startWake(): Promise<WakeInfo>;
  stopWake(): Promise<WakeInfo>;
  openOverlaySettings(): Promise<void>;
  openBatterySettings(): Promise<void>;
  launchMode(): Promise<{ wake: boolean }>;
  finishWake(): Promise<void>;
  pauseWake(): Promise<void>;
  resumeWake(): Promise<void>;
  keepScreenOn(o: { on: boolean }): Promise<void>;
  endCall(): Promise<{ ended: boolean }>;
  audioRoute(o: { on: boolean }): Promise<{ bluetooth: boolean }>;
  listen(o: { language: string }): Promise<void>;
  stopListen(): Promise<void>;
  lastCrash(): Promise<{ text: string; time: number }>;
  clearCrash(): Promise<void>;
  addListener(event: string, cb: (d: { text?: string; code?: number }) => void): Promise<{ remove(): Promise<void> }>;
}>("UnicPhone");

export const phone = {
  listContacts: async (): Promise<Contact[]> => (await Native.listContacts()).contacts || [],
  call: async (number: string): Promise<void> => { await Native.call({ number }); },
  /** Rend true si le SMS est seulement préparé dans l'appli Messages (autorisation SMS bloquée) : le patron touche « Envoyer ». */
  endCall: async (): Promise<boolean> => (await Native.endCall()).ended,
  sendSms: async (number: string, text: string, composer = false): Promise<boolean> => !!((await Native.sendSms({ number, text, composer })) as { composerOnly?: boolean } | undefined)?.composerOnly,
};

/** Casque / AirPods : le micro passe par le casque pendant la conversation (sans casque : aucun effet). */
export const audioRoute = (on: boolean): Promise<unknown> => Native.audioRoute({ on }).catch(() => null);

/** Écoute native (une phrase) : « ready » = micro vraiment ouvert ; les erreurs arrivent avec leur code. */
export const ear = {
  start: (language = "fr-FR"): Promise<void> => Native.listen({ language }),
  stop: (): Promise<void> => Native.stopListen().catch(() => {}),
  on: (event: "ready" | "speech" | "partial" | "final" | "endSpeech" | "error", cb: (d: { text?: string; code?: number }) => void) => Native.addListener(event, cb),
};

/** Dernier plantage de l'appli (diagnostic). */
export const crashApi = {
  last: async (): Promise<{ text: string; time: number }> => Native.lastCrash(),
  clear: async (): Promise<void> => { await Native.clearCrash(); },
};

export const notifApi = {
  list: async (): Promise<Notif[]> => (await Native.listNotifications()).notifications || [],
  enabled: async (): Promise<boolean> => (await Native.notificationAccess()).enabled,
  openSettings: async (): Promise<void> => { await Native.openNotificationSettings(); },
  locked: async (): Promise<boolean> => (await Native.isLocked()).locked,
  lockScreenMode: async (on: boolean): Promise<void> => { await Native.setLockScreenMode({ on }); },
};

export const wakeApi = {
  status: async (): Promise<WakeInfo> => Native.wakeStatus(),
  start: async (): Promise<WakeInfo> => Native.startWake(),
  stop: async (): Promise<WakeInfo> => Native.stopWake(),
  openOverlay: async (): Promise<void> => { await Native.openOverlaySettings(); },
  openBattery: async (): Promise<void> => { await Native.openBatterySettings(); },
  /** Vrai si l'écran a été ouvert par « Hey UniC ». */
  isWakeLaunch: async (): Promise<boolean> => (await Native.launchMode()).wake,
  finish: async (): Promise<void> => { await Native.finishWake(); },
  /** L'interprète est ouvert : « Hey UniC » se tait (puis reprend). */
  pause: async (): Promise<void> => { await Native.pauseWake(); },
  resume: async (): Promise<void> => { await Native.resumeWake(); },
  keepScreenOn: async (on: boolean): Promise<void> => { await Native.keepScreenOn({ on }); },
};

const PHONE_LOCK_KEY = "unic.phoneWhenLocked";
/** Appeler / écrire un SMS par la voix téléphone verrouillé : NON par défaut (n'importe qui près du téléphone pourrait le dire). */
export const getPhoneWhenLocked = (): boolean => { try { return localStorage.getItem(PHONE_LOCK_KEY) === "1"; } catch { return false; } };
export const setPhoneWhenLocked = (on: boolean): void => { try { localStorage.setItem(PHONE_LOCK_KEY, on ? "1" : "0"); } catch { /* ignoré */ } };

const LOCK_KEY = "unic.readWhenLocked";
/** Lire les notifications même téléphone verrouillé : oui par défaut (demande du patron), réglable dans Voix. */
export const getReadWhenLocked = (): boolean => { try { return localStorage.getItem(LOCK_KEY) !== "0"; } catch { return true; } };
export const setReadWhenLocked = (on: boolean): void => { try { localStorage.setItem(LOCK_KEY, on ? "1" : "0"); } catch { /* ignoré */ } };
