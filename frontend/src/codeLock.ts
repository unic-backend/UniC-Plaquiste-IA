/** Code de l'appli : un code à chiffres demandé à l'ouverture et au retour après une absence. FACULTATIF (coupé par défaut).
 *
 * - Propre à cet appareil : seule l'empreinte du code est gardée (PBKDF2-SHA-256 salé), jamais le code.
 * - Essais faux : après 5, attente de 30 s, doublée à chaque nouvel essai faux (15 min au plus).
 * - Code oublié : on se déconnecte (le code est retiré) et on se reconnecte avec le mot de passe.
 * C'est une barrière d'écran contre la personne qui prend le téléphone déverrouillé, pas un chiffrement des données. */

export type LockStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type LockConfig = { salt: string; hash: string; len: number; idleMs: number };

const KEY = "unic.applock";
const FAILS_KEY = "unic.applock.fails";
const ITERATIONS = 100_000;
export const MIN_LEN = 4;
export const MAX_LEN = 8;
export const FREE_TRIES = 5;
const FIRST_WAIT_MS = 30_000;
const MAX_WAIT_MS = 15 * 60_000;
export const IDLE_CHOICES = [{ ms: 0, label: "Tout de suite" }, { ms: 60_000, label: "Après 1 minute" }, { ms: 5 * 60_000, label: "Après 5 minutes" }];

const store = (): LockStore | null => { try { return localStorage; } catch { return null; } };
const read = <T>(s: LockStore | null, key: string): T | null => { try { const v = s?.getItem(key); return v ? (JSON.parse(v) as T) : null; } catch { return null; } };
const hex = (b: ArrayBuffer | Uint8Array) => Array.from(b instanceof Uint8Array ? b : new Uint8Array(b), (x) => x.toString(16).padStart(2, "0")).join("");
const unhex = (h: string) => new Uint8Array((h.match(/../g) || []).map((x) => parseInt(x, 16)));

/** Le chiffrement du navigateur est là (https, appli installée). Sinon, l'option n'est pas proposée. */
export const supported = (): boolean => typeof crypto !== "undefined" && !!crypto.subtle;
export const validPin = (pin: string): boolean => new RegExp(`^\\d{${MIN_LEN},${MAX_LEN}}$`).test(pin);

async function derive(pin: string, salt: Uint8Array<ArrayBuffer>): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pin), "PBKDF2", false, ["deriveBits"]);
  return hex(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: ITERATIONS }, key, 256));
}

export function config(s: LockStore | null = store()): LockConfig | null {
  const c = read<LockConfig>(s, KEY);
  return c && c.salt && c.hash ? c : null;
}

export const enabled = (s: LockStore | null = store()): boolean => !!config(s);

export async function setPin(pin: string, idleMs: number, s: LockStore | null = store()): Promise<void> {
  if (!validPin(pin)) throw new Error(`Le code doit faire de ${MIN_LEN} à ${MAX_LEN} chiffres.`);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  s?.setItem(KEY, JSON.stringify({ salt: hex(salt), hash: await derive(pin, salt), len: pin.length, idleMs } satisfies LockConfig));
  s?.removeItem(FAILS_KEY);
}

export function setIdle(idleMs: number, s: LockStore | null = store()): void {
  const c = config(s);
  if (c) s?.setItem(KEY, JSON.stringify({ ...c, idleMs }));
}

export function clear(s: LockStore | null = store()): void {
  s?.removeItem(KEY);
  s?.removeItem(FAILS_KEY);
}

/** Temps d'attente imposé avant le prochain essai (0 = on peut essayer). */
export function waitMs(now = Date.now(), s: LockStore | null = store()): number {
  const f = read<{ n: number; until: number }>(s, FAILS_KEY);
  return f && f.until > now ? f.until - now : 0;
}

export async function check(pin: string, now = Date.now(), s: LockStore | null = store()): Promise<{ ok: boolean; waitMs: number }> {
  const c = config(s);
  if (!c) return { ok: true, waitMs: 0 };
  const wait = waitMs(now, s);
  if (wait) return { ok: false, waitMs: wait };
  const given = await derive(pin, unhex(c.salt));
  let same = given.length === c.hash.length ? 0 : 1;   // comparaison sans sortie anticipée
  for (let i = 0; i < given.length; i++) same |= given.charCodeAt(i) ^ (c.hash.charCodeAt(i) || 0);
  if (same === 0) { s?.removeItem(FAILS_KEY); return { ok: true, waitMs: 0 }; }
  const n = (read<{ n: number }>(s, FAILS_KEY)?.n || 0) + 1;
  const pause = n < FREE_TRIES ? 0 : Math.min(FIRST_WAIT_MS * 2 ** (n - FREE_TRIES), MAX_WAIT_MS);
  s?.setItem(FAILS_KEY, JSON.stringify({ n, until: now + pause }));
  return { ok: false, waitMs: pause };
}

/** Faut-il redemander le code au retour ? (absence au moins égale au délai choisi) */
export const dueAfter = (hiddenAt: number | null, now: number, idleMs: number): boolean => hiddenAt !== null && now - hiddenAt >= idleMs;
