import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as I from "./Icons";
import { api, fetchBlobUrl, shareDocument } from "./api";

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

/** Schéma dessiné par l'IA (PNG) : affiché dans la conversation, partageable. */
export function DiagramCard({ id, filename, title }: { id: string; filename: string; title?: string }) {
  const [src, setSrc] = useState("");
  const [err, setErr] = useState("");
  const url = `/api/artifacts/${id}/download`;
  useEffect(() => {
    let off = "";
    fetchBlobUrl(url).then((u) => { off = u; setSrc(u); }).catch((e) => setErr(e?.message || "Image introuvable"));
    return () => { if (off) URL.revokeObjectURL(off); };
  }, [url]);
  return (
    <figure className="diagram">
      {src ? <img src={src} alt={title || "Schéma"} /> : <span className="hint">{err || "Chargement du schéma…"}</span>}
      <figcaption>
        <span>{title || "Schéma"} · dessin, pas un plan d'exécution</span>
        <ShareButton url={url} filename={filename} />
      </figcaption>
    </figure>
  );
}

/** Fichier modifié par l'assistant (PDF, Word, Excel) : aperçu des pages pour un PDF, téléchargement et partage. L'original reste intact. */
export function FileCard({ id, filename, mime, size }: { id: string; filename: string; mime: string; size?: number }) {
  const [imgs, setImgs] = useState<string[] | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");
  const url = `/api/artifacts/${id}/download`;
  const isPdf = mime === "application/pdf";
  const kb = size ? (size > 1048576 ? `${(size / 1048576).toFixed(1)} Mo` : `${Math.max(1, Math.round(size / 1024))} Ko`) : "";
  const show = () => {
    setOpen(true);
    if (!imgs) api.preview(id).then((r) => setImgs(r.images)).catch((e: Error) => setErr(e.message));
  };
  return (
    <div className="art file-card">
      <div>
        <b>{filename}</b>
        <span>Modifié par UniC · l'original est intact{kb ? ` · ${kb}` : ""}</span>
      </div>
      <div className="art-actions">
        {isPdf && <button className="btn btn-line btn-small" onClick={show}>Aperçu</button>}
        <ShareButton url={url} filename={filename} />
      </div>
      {open && createPortal(
        <div className="preview-back" role="dialog" aria-label={`Aperçu ${filename}`}>
          <div className="preview-head">
            <button className="tool" aria-label="Fermer l'aperçu" onClick={() => setOpen(false)}>✕</button>
            <b>{filename}</b>
            <span />
          </div>
          <div className="preview-body">
            {!imgs && !err && <p className="hint">Chargement de l'aperçu…</p>}
            {err && <p className="error">{err}</p>}
            {imgs?.map((src, i) => <img key={i} src={src} alt={`Page ${i + 1}`} />)}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
