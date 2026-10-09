import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";
import * as B from "./Brands";
import * as I from "./Icons";

/** Raccourcis vers les comptes et outils du patron : un clic pose la question à l'IA. */
type Shortcut = {
  id: string;
  label: string;
  icon: (p: { size?: number }) => JSX.Element;
  prompt?: string;     // question envoyée à l'IA
  need?: string;       // connecteur requis (état réel venant du serveur)
  setup?: string;      // page pour le brancher
  soon?: boolean;      // pas encore branché dans UniC AI
};

export const SHORTCUTS: Shortcut[] = [
  { id: "briefing", label: "Briefing", icon: I.Sun, prompt: "briefing" },
  { id: "mail", label: "Gmail", icon: B.Gmail, prompt: "Résume mes derniers e-mails importants.", need: "email", setup: "/courrier" },
  { id: "agenda", label: "Agenda", icon: B.Calendar, prompt: "Qu'est-ce que j'ai à l'agenda cette semaine ?" },
  { id: "unpaid", label: "Impayés", icon: I.Receipt, prompt: "Quelles factures sont impayées ?" },
  { id: "notes", label: "Notes", icon: I.Note, prompt: "Montre-moi mes notes : ce que tu as retenu et mes consignes." },
  { id: "google", label: "Avis Google", icon: B.GoogleG, prompt: "Montre les derniers avis Google.", need: "gbp", setup: "/google" },
  { id: "site", label: "Site · GitHub", icon: B.GitHub, need: "website", setup: "/reseaux" },
  { id: "canva", label: "Canva", icon: B.Canva, soon: true },
  { id: "gcal", label: "Google Agenda", icon: B.Calendar, soon: true },
];

let cache: Record<string, boolean> | null = null;

/** État réel des connecteurs (gardé le temps de la session, rafraîchi en arrière-plan). */
export function useConnectors(): Record<string, boolean> | null {
  const [c, setC] = useState(cache);
  useEffect(() => {
    let alive = true;
    api.connectors().then((x) => { cache = x; if (alive) setC(x); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  return c;
}

const ready = (s: Shortcut, c: Record<string, boolean> | null) => !s.soon && (!s.need || !!c?.[s.need]);

/** Pastilles au-dessus de la saisie : visibles sur une conversation vide, disparaissent dès qu'on écrit. */
export function QuickChips({ show, onAsk }: { show: boolean; onAsk: (prompt: string) => void }) {
  const c = useConnectors();
  const items = SHORTCUTS.filter((s) => s.prompt && ready(s, c)).slice(0, 6);
  return (
    <div className={`quick-chips ${show ? "" : "gone"}`} aria-hidden={!show}>
      {items.map((s) => (
        <button key={s.id} className="quick-chip" tabIndex={show ? 0 : -1} onClick={() => onAsk(s.prompt!)}>
          <s.icon size={16} /> {s.label}
        </button>
      ))}
    </div>
  );
}

/** Liste complète (feuille « + » › Plus) : branché = question à l'IA ; sinon = page pour le brancher. */
export function AppsList({ onAsk, onClose }: { onAsk: (prompt: string) => void; onClose: () => void }) {
  const c = useConnectors();
  const nav = useNavigate();
  return (
    <div className="apps-list">
      {SHORTCUTS.map((s) => {
        const ok = ready(s, c);
        const state = s.soon ? "Bientôt" : ok ? (s.need ? "Connecté" : "") : c ? "Non connecté" : "…";
        const act = () => {
          if (s.soon) return;
          onClose();
          if (ok && s.prompt) onAsk(s.prompt);
          else if (s.setup) nav(s.setup);
        };
        return (
          <button key={s.id} className={`app-row ${s.soon ? "soon" : ""}`} disabled={s.soon} onClick={act}>
            <span className="app-ic"><s.icon size={20} /></span>
            <b>{s.label}</b>
            {state && <span className={`app-state ${ok ? "on" : ""}`}>{state}</span>}
          </button>
        );
      })}
      <p className="hint">Rien n'est envoyé ni publié sans ton clic.</p>
    </div>
  );
}
