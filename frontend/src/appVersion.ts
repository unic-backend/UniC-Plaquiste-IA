/** Version de l'interface : celle de cette appli (APK) comparée à celle en ligne sur le serveur. Pur, testé dans tests/appVersion.check.ts. */

/** Empreinte valide : 12 caractères hexadécimaux (vite.config.ts). Toute autre valeur = inconnue, jamais d'alerte. */
const BUILD_RE = /^[0-9a-f]{12}$/;

/** Vrai quand le serveur a une interface plus récente que celle de l'appli et que le patron n'a pas mis de côté cette version-là. */
export function updateNeeded(own: string, online: unknown, dismissed: string | null): boolean {
  if (typeof online !== "string" || !BUILD_RE.test(online) || !BUILD_RE.test(own)) return false;
  return online !== own && online !== dismissed;
}
