import { registerPlugin } from "@capacitor/core";
import type { Contact } from "./phoneMatch";

/** Pont vers le code Android (UnicPhonePlugin.java) : contacts, appel, SMS. Absent sur le web. */
const Native = registerPlugin<{
  listContacts(): Promise<{ contacts: Contact[] }>;
  call(o: { number: string }): Promise<{ dialedOnly?: boolean } | void>;
  sendSms(o: { number: string; text: string }): Promise<void>;
}>("UnicPhone");

export const phone = {
  listContacts: async (): Promise<Contact[]> => (await Native.listContacts()).contacts || [],
  call: async (number: string): Promise<void> => { await Native.call({ number }); },
  sendSms: async (number: string, text: string): Promise<void> => { await Native.sendSms({ number, text }); },
};
