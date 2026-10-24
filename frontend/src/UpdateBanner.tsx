import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, isNative } from "./api";
import { updateNeeded } from "./appVersion";

const KEY = "unic.update.dismissed";
const EVERY_MS = 30 * 60 * 1000;

function dismissed(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

/** Appli du téléphone : prévient quand le serveur a une interface plus récente que celle de l'APK installé.
 * (Le site web se met à jour tout seul ; l'APK, lui, garde l'interface avec laquelle il a été construit.) */
export default function UpdateBanner() {
  const [online, setOnline] = useState<string | null>(null);
  const nav = useNavigate();
  useEffect(() => {
    if (!isNative) return;
    const check = () => api.ping().then((p) => setOnline(updateNeeded(__APP_BUILD__, p.web_build, dismissed()) ? p.web_build ?? null : null)).catch(() => {});
    check();
    const t = setInterval(check, EVERY_MS);
    const onShow = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onShow);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", onShow); };
  }, []);
  if (!online) return null;
  const later = () => { try { localStorage.setItem(KEY, online); } catch { /* ignoré */ } setOnline(null); };
  return (
    <div className="update-banner" role="status">
      <span>Nouvelle version de l'appli disponible. Installe le nouvel APK pour l'avoir sur ce téléphone.</span>
      <div className="row-actions">
        <button className="btn btn-copper btn-small" onClick={() => { later(); nav("/atelier"); }}>Obtenir l'APK</button>
        <button className="btn btn-line btn-small" onClick={later}>Plus tard</button>
      </div>
    </div>
  );
}
