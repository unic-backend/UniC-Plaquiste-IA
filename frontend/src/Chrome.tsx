import * as I from "./Icons";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, downloadAuth, net, type Post } from "./api";

/* ---------- Barre de page avec bouton retour (toutes les pages hors conversation) ---------- */

const TITLES: Record<string, string> = {
  parametres: "Paramètres", entreprise: "Informations société", courrier: "Courrier", reseaux: "Réseaux & Google", voix: "Voix",
  memoire: "Mémoire", sante: "Moteur & santé", materiaux: "Matériaux & prix", clients: "Clients",
  fournisseurs: "Fournisseurs", devis: "Devis", factures: "Factures", agenda: "Agenda", prospects: "Prospects", commandes: "Bons de commande", suivi: "Suivi des encaissements",
  livraisons: "Bons de livraison", chantiers: "Chantiers", documents: "Fichiers reçus",
};

/** Page d'où l'on vient logiquement (le retour matériel d'Android suit, lui, l'historique). */
export function parentPath(path: string): string {
  if (path === "/parametres") return "/";
  if (path === "/parametres/entreprise") return "/parametres";
  if (path === "/suivi") return "/";
  if (/^\/(devis|factures|commandes|livraisons|chantiers|suivi)\/[^/]+$/.test(path)) return "/" + path.split("/")[1];
  return "/parametres";
}

export function PageBar() {
  const { pathname } = useLocation();
  const nav = useNavigate();
  const parts = pathname.split("/").filter(Boolean);
  const title = TITLES[parts[parts.length - 1]] ?? TITLES[parts[0]] ?? "";
  const back = () => (window.history.length > 1 ? nav(-1) : nav(parentPath(pathname)));
  return (
    <div className="pagebar">
      <button className="pagebar-back" onClick={back} aria-label="Retour">
        <I.Back size={20} /> Retour
      </button>
      <span className="pagebar-title">{title}</span>
      <button className="pagebar-chat" onClick={() => nav("/")}>
        Conversation
      </button>
    </div>
  );
}

/* ---------- Indicateur « l'IA écrit » ---------- */

export function Typing({ deep, web, status, liveHtml }: { deep: boolean; web: boolean; status?: string; liveHtml?: string }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStep((s) => s + 1), 2500);
    return () => clearInterval(t);
  }, []);
  const phrases = deep
    ? ["Je réfléchis en profondeur…", "J'analyse le problème…", "Je vérifie mon raisonnement…"]
    : web
      ? ["Je réfléchis…", "Je consulte les sources si besoin…", "Je rédige la réponse…"]
      : ["Je réfléchis…", "Je rédige la réponse…"];
  if (liveHtml) {
    return (
      <div className="msg assistant">
        <div className="avatar">U</div>
        <div className="bubble typing"><div className="md" dangerouslySetInnerHTML={{ __html: liveHtml }} /></div>
      </div>
    );
  }
  return (
    <div className="msg assistant enter">
      <div className="avatar">U</div>
      <div className="bubble typing" role="status" aria-live="polite">
        <span className="dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="typing-text">{status || phrases[step % phrases.length]}</span>
      </div>
    </div>
  );
}

/* ---------- Connecteurs utilisés par l'IA ---------- */

const TOOL_LABELS: Record<string, string> = {
  read_inbox: "Courrier consulté", search_inbox: "Boîte mail fouillée", business_calc: "Calcul d'affaires fait", read_email: "E-mail lu", save_email_reply_draft: "Réponse e-mail préparée",
  list_google_reviews: "Avis Google consultés", google_profile_audit: "Fiche Google auditée",
  save_google_review_reply_draft: "Réponse à un avis préparée", save_social_post_draft: "Publication préparée",
  list_social_posts: "Publications consultées",
};

export function ToolChips({ caps }: { caps?: string[] }) {
  const tools = (caps || []).filter((c) => c.startsWith("tool:"));
  if (!tools.length) return null;
  return (
    <div className="tool-chips">
      {tools.map((t) => (
        <span className="tool-chip" key={t}><I.Plug size={14} /> {TOOL_LABELS[t.slice(5)] ?? t.slice(5)}</span>
      ))}
    </div>
  );
}

/* ---------- Brouillons préparés par l'IA, validés d'un geste dans la conversation ---------- */

function EmailDraftCard({ id }: { id: string }) {
  const [d, setD] = useState<any>(null);
  const [canSend, setCanSend] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<{ to_addr: string; subject: string; body: string } | null>(null);
  const load = () => api.emails().then((rows) => setD(rows.find((r: any) => r.id === id) ?? null));
  useEffect(() => {
    load();
    net.mailStatus().then((s) => setCanSend(s.send)).catch(() => setCanSend(false));
  }, [id]);
  if (!d) return null;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      setMsg(ok);
      await load();
    } catch (e: any) {
      setMsg(e.message);
      await load();
    } finally {
      setBusy(false);
    }
  };
  const save = () => act(async () => { if (edit) await net.editDraft(id, edit); setEdit(null); }, "Modifié.");
  const removeFile = (fid: string) => act(() => net.editDraft(id, { attachments: d.attachments.filter((a: any) => a.id !== fid).map((a: any) => a.id) }), "Pièce jointe retirée.");
  const noAddress = !/@/.test(d.to || "");
  return (
    <div className="draft-card">
      <div className="draft-card-head"><b>✉️ {d.reply ? "Brouillon de réponse" : "Brouillon d'e-mail"}</b><span className="badge">{d.status}</span></div>
      {edit ? (
        <div className="form-grid">
          <label>À<input type="email" value={edit.to_addr} placeholder="adresse@exemple.com" onChange={(e) => setEdit({ ...edit, to_addr: e.target.value })} /></label>
          <label>Objet<input value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} /></label>
          <label>Texte<textarea rows={8} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} /></label>
        </div>
      ) : (
        <>
          <div className="hint">À : {d.to || <b>adresse à compléter</b>} · {d.subject}</div>
          <p className="post-body">{d.body}</p>
        </>
      )}
      {d.attachments?.length > 0 && (
        <div className="hint">
          📎 {d.attachments.map((a: any) => (
            <span key={a.id} style={{ marginRight: 10 }}>
              <button className="btn btn-ghost btn-small" onClick={() => downloadAuth(`/api/artifacts/${a.id}/download`, a.filename)}>{a.filename}</button>
              {d.status === "draft" && <button className="btn btn-ghost btn-small" aria-label={`Retirer ${a.filename}`} disabled={busy} onClick={() => removeFile(a.id)}>✕</button>}
            </span>
          ))}
        </div>
      )}
      <div className="toolbar">
        {d.status === "draft" && !edit && <button className="btn btn-line btn-small" onClick={() => setEdit({ to_addr: d.to || "", subject: d.subject, body: d.body })}>Modifier</button>}
        {edit && <button className="btn btn-copper btn-small" disabled={busy} onClick={save}>Enregistrer</button>}
        {edit && <button className="btn btn-ghost btn-small" onClick={() => setEdit(null)}>Annuler</button>}
        {d.status === "draft" && !edit && canSend && (
          <button className="btn btn-copper btn-small" disabled={busy || noAddress}
            onClick={() => act(async () => { await net.approveDraft(id); await net.sendDraft(id); }, "E-mail envoyé.")}>
            {noAddress ? "Ajoute l'adresse pour envoyer" : "Valider et envoyer"}
          </button>
        )}
        {d.status === "draft" && !edit && !canSend && (
          <button className="btn btn-copper btn-small" disabled={busy || noAddress} onClick={() => act(() => net.approveDraft(id), "Approuvé.")}>Approuver</button>
        )}
        {d.status === "approved" && (
          <button className="btn btn-copper btn-small" disabled={!canSend || busy} onClick={() => act(() => net.sendDraft(id), "E-mail envoyé.")}>
            {canSend ? "Envoyer" : "Envoi NON DISPONIBLE (SMTP)"}
          </button>
        )}
        {d.status === "sent" && <span className="badge">Envoyé</span>}
        {!edit && <button className="btn btn-ghost btn-small" onClick={() => navigator.clipboard?.writeText(d.body)}>Copier</button>}
      </div>
      {msg && <div className="hint" role="status">{msg}</div>}
    </div>
  );
}

function SocialDraftCard({ id }: { id: string }) {
  const [p, setP] = useState<Post | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => net.posts().then((rows) => setP(rows.find((r) => r.id === id) ?? null));
  useEffect(() => {
    load();
  }, [id]);
  if (!p) return null;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg(ok);
      load();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const google = p.platform === "google_business";
  return (
    <div className="draft-card">
      <div className="draft-card-head">
        <b>{p.kind === "reply" ? <><I.Chat size={16} /> Réponse préparée</> : <><I.Megaphone size={16} /> Publication préparée</>} · {p.platform}</b>
        <span className="badge">{p.status}</span>
      </div>
      {p.in_reply_to && <div className="hint">En réponse à : « {p.in_reply_to.slice(0, 160)} »</div>}
      <p className="post-body">{p.body}</p>
      <div className="toolbar">
        {p.status === "draft" && <button className="btn btn-line btn-small" onClick={() => act(() => net.advance(id), "En revue.")}>Passer en revue</button>}
        {p.status === "review" && <button className="btn btn-copper btn-small" onClick={() => act(() => net.advance(id), "Approuvé.")}>Approuver</button>}
        {p.status === "approved" && google && <button className="btn btn-copper btn-small" onClick={() => act(() => net.publish(id), "Publié sur Google.")}>Publier sur Google</button>}
        {p.status === "approved" && !google && <button className="btn btn-line btn-small" onClick={() => act(() => net.advance(id), "Marqué publié.")}>Marquer publié (manuel)</button>}
        <button className="btn btn-ghost btn-small" onClick={() => navigator.clipboard?.writeText(p.body)}>Copier</button>
      </div>
      {msg && <div className="hint">{msg}</div>}
    </div>
  );
}

export function DraftCards({ drafts }: { drafts?: { kind: string; id: string }[] }) {
  if (!drafts?.length) return null;
  return (
    <>
      {drafts.map((d) => (d.kind === "email" ? <EmailDraftCard key={d.id} id={d.id} /> : <SocialDraftCard key={d.id} id={d.id} />))}
    </>
  );
}

/* ---------- Historique groupé par date ---------- */

export function groupByDate<T extends { updated_at?: string }>(rows: T[]): { label: string; rows: T[] }[] {
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = startOfDay(new Date());
  const day = 86_400_000;
  const buckets: Record<string, T[]> = {};
  const order = ["Aujourd'hui", "Hier", "7 derniers jours", "Plus ancien"];
  for (const r of rows) {
    const t = r.updated_at ? startOfDay(new Date(r.updated_at)) : 0;
    const label = t >= today ? order[0] : t >= today - day ? order[1] : t >= today - 7 * day ? order[2] : order[3];
    (buckets[label] ||= []).push(r);
  }
  return order.filter((l) => buckets[l]).map((l) => ({ label: l, rows: buckets[l] }));
}
