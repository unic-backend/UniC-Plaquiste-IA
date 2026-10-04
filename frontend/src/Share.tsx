import { useEffect, useState } from "react";
import * as I from "./Icons";
import { api, shareDocument } from "./api";

/** Bouton « Partager » : ouvre la feuille de partage Android avec le PDF (WhatsApp, e-mail…). */
export function ShareButton({ url, filename, text = "", className = "btn btn-line btn-small", label = "Partager" }:
  { url: string; filename: string; text?: string; className?: string; label?: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async () => {
    setBusy(true); setErr("");
    try { await shareDocument(url, filename, text); } catch (e: any) { if (!/cancel|abort/i.test(String(e?.message))) setErr(e?.message || "Partage impossible"); } finally { setBusy(false); }
  };
  return (
    <>
      <button className={className} disabled={busy} onClick={go}><I.Send size={15} /> {busy ? "Préparation…" : label}</button>
      {err && <span className="error">{err}</span>}
    </>
  );
}

const words = (t: string) => t.trim().split(/\s+/).filter(Boolean).length;

/** Lettre d'accompagnement du devis approuvé : 250 mots maximum, modifiable, partagée avec le PDF. */
export function CoverLetterBox({ quote, url, filename, onChanged }: { quote: any; url: string | null; filename: string; onChanged: () => void }) {
  const [text, setText] = useState<string>(quote.cover_letter || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { setText(quote.cover_letter || ""); }, [quote.cover_letter]);
  const n = words(text);
  const dirty = text.trim() !== (quote.cover_letter || "").trim();
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg("");
    try { await fn(); setMsg(ok); onChanged(); } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  return (
    <section className="card-box cover">
      <label>Lettre d'accompagnement</label>
      {!quote.cover_letter && !text ? (
        <button className="btn btn-copper btn-small" disabled={busy} onClick={() => run(() => api.regenerateCoverLetter(quote.id), "Lettre prête.")}>Préparer la lettre</button>
      ) : (
        <>
          <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} aria-label="Lettre d'accompagnement" />
          <p className={n > 250 ? "error" : "hint"}>{n} / 250 mots</p>
          <div className="toolbar">
            {dirty && <button className="btn btn-copper btn-small" disabled={busy || n > 250} onClick={() => run(() => api.saveCoverLetter(quote.id, text), "Enregistrée.")}>Enregistrer</button>}
            <button className="btn btn-line btn-small" onClick={async () => { try { await navigator.clipboard.writeText(text); setMsg("Lettre copiée."); } catch { setMsg("Copie impossible."); } }}>Copier</button>
            <button className="btn btn-line btn-small" disabled={busy} onClick={() => { if (!dirty || window.confirm("Remplacer le texte par une nouvelle lettre ?")) run(() => api.regenerateCoverLetter(quote.id), "Nouvelle lettre prête."); }}>Régénérer</button>
            {url && <ShareButton url={url} filename={filename} text={text} className="btn btn-copper btn-small" label="Partager avec le PDF" />}
          </div>
        </>
      )}
      {msg && <p className="hint">{msg}</p>}
    </section>
  );
}
