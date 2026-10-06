import { registerPlugin } from "@capacitor/core";
import type { Contact } from "./phoneMatch";
import type { Notif } from "./notifs";

/** Pont vers le code Android (UnicPhonePlugin.java) : contacts, appel, SMS. Absent sur le web. */
const Native = registerPlugin<{
  listContacts(): Promise<{ contacts: Contact[] }>;
  call(o: { number: string }): Promise<{ dialedOnly?: boolean } | void>;
  sendSms(o: { number: string; text: string }): Promise<{ composerOnly?: boolean } | void>;
  notificationAccess(): Promise<{ enabled: boolean }>;
  openNotificationSettings(): Promise<void>;
  listNotifications(): Promise<{ notifications: Notif[] }>;
  isLocked(): Promise<{ locked: boolean }>;
  setLockScreenMode(o: { on: boolean }): Promise<void>;
}>("UnicPhone");

export const phone = {
  listContacts: async (): Promise<Contact[]> => (await Native.listContacts()).contacts || [],
  call: async (number: string): Promise<void> => { await Native.call({ number }); },
  /** Rend true si le SMS est seulement préparé dans l'appli Messages (autorisation SMS bloquée) : le patron touche « Envoyer ». */
  sendSms: async (number: string, text: string): Promise<boolean> => !!((await Native.sendSms({ number, text })) as { composerOnly?: boolean } | undefined)?.composerOnly,
};

export const notifApi = {
  list: async (): Promise<Notif[]> => (await Native.listNotifications()).notifications || [],
  enabled: async (): Promise<boolean> => (await Native.notificationAccess()).enabled,
  openSettings: async (): Promise<void> => { await Native.openNotificationSettings(); },
  locked: async (): Promise<boolean> => (await Native.isLocked()).locked,
  lockScreenMode: async (on: boolean): Promise<void> => { await Native.setLockScreenMode({ on }); },
};

const LOCK_KEY = "unic.readWhenLocked";
/** Lire les notifications même téléphone verrouillé : oui par défaut (demande du patron), réglable dans Voix. */
export const getReadWhenLocked = (): boolean => { try { return localStorage.getItem(LOCK_KEY) !== "0"; } catch { return true; } };
export const setReadWhenLocked = (on: boolean): void => { try { localStorage.setItem(LOCK_KEY, on ? "1" : "0"); } catch { /* ignoré */ } };
