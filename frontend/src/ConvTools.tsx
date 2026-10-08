import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type ChatMessage, type Conv } from "./api";
import { AttachRow, type Attach } from "./Attach";
import { FileCard, ShareButton } from "./Share";
import * as I from "./Icons";

/** Menu en haut à droite d'une conversation : fichiers, épingler, archiver, supprimer. */
export function ConvMenu({ conv, onChange, onGone }: { conv: Conv; onChange: (n: Partial<Conv>) => void; onGone: () => void }) {
  const [menu, setMenu] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState("");
  const btn = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; right: number }>({ top: 64, right: 12 });
  useEffect(() => {   // le retour du téléphone ferme d'abord le menu ou la feuille
    if (!menu && !sheet) return;
    const h = (e: Event) => { e.preventDefault(); setMenu(false); setSheet(false); setConfirm(false); };
    window.addEventListener("unic:back", h);
    return () => window.removeEventListener("unic:back", h);
  }, [menu, sheet]);
  const close = () => { setMenu(false); setConfirm(false); setErr(""); };
  const run = async (fn: () => Promise<void>) => { try { await fn(); close(); } catch (e: any) { setErr(e?.message || "Erreur"); } };
  return (
    <div className="conv-tools">
      <button ref={btn} className="icon-btn" aria-label="Options de la conversation" aria-expanded={menu} onClick={() => {
        const r = btn.current?.getBoundingClientRect();
        if (r) setPos({ top: Math.round(r.bottom + 8), right: Math.max(8, Math.round(window.innerWidth - r.right)) });
        setMenu((m) => !m); setConfirm(false);
      }}><I.More size={22} /></button>
      {menu && createPortal(   // hors de la barre du haut : au-dessus de tout, jamais sous le texte de la conversation
        <>
          <div className="conv-tools-shade" onClick={close} />
          <div className="conv-tools-menu" role="menu" style={{ top: pos.top, right: pos.right }}>
            {!confirm ? (
              <>
                <button role="menuitem" onClick={() => { setMenu(false); setSheet(true); }}><I.File size={18} /> Fichiers de la conversation</button>
                <button role="menuitem" onClick={() => run(async () => { const r = await api.patchConversation(conv.id, { pinned: !conv.pinned }); onChange({ pinned: r.pinned }); })}>
                  <I.Pin size={18} /> {conv.pinned ? "Désépingler" : "Épingler"}</button>
                <button role="menuitem" onClick={() => run(async () => { await api.patchConversation(conv.id, { archived: true }); onGone(); })}><I.ArrowDown size={18} /> Archiver</button>
                <button role="menuitem" className="danger" onClick={() => setConfirm(true)}><I.Trash size={18} /> Supprimer</button>
              </>
            ) : (
              <div className="conv-tools-confirm">
                <p>Supprimer cette conversation pour toujours ?</p>
                <div className="row-actions">
                  <button className="btn btn-small danger-btn" onClick={() => run(async () => { await api.deleteConversation(conv.id); onGone(); })}>Supprimer</button>
                  <button className="btn btn-line btn-small" onClick={() => setConfirm(false)}>Annuler</button>
                </div>
              </div>
            )}
            {err && <p className="error">{err}</p>}
          </div>
        </>,
        document.body,
      )}
      {sheet && createPortal(<ConvFiles id={conv.id} title={conv.title} onClose={() => setSheet(false)} />, document.body)}
    </div>
  );
}

type Made = { id: string; filename: string; mime?: string; size?: number; url?: string };

/** Tout ce qui est passé dans cette conversation : fichiers et photos reçus, documents créés par UniC. */
function ConvFiles({ id, title, onClose }: { id: string; title: string; onClose: () => void }) {
  const [msgs, setMsgs] = useState<ChatMessage[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.getConversation(id).then((c) => setMsgs(c.messages)).catch((e) => setErr(e?.message || "Erreur")); }, [id]);
  const got: Attach[] = [], made: Made[] = [], seen = new Set<string>();
  for (const m of msgs || []) {
    for (const f of m.meta?.files || []) if (f.id && !seen.has(f.id)) { seen.add(f.id); got.push({ name: f.filename, mime: f.mime, id: f.id }); }
    for (const a of m.meta?.artifacts || []) if (a.id && !seen.has(a.id)) { seen.add(a.id); made.push({ id: a.id, filename: a.filename, mime: a.mime_type, size: a.size, url: a.download_url }); }
    for (const f of m.meta?.structured?.files || []) if (f.id && !seen.has(f.id)) { seen.add(f.id); made.push({ id: f.id, filename: f.filename, mime: f.mime, size: f.size }); }
  }
  return (
    <div className="sheet-back" role="dialog" aria-label="Fichiers de la conversation" onClick={onClose}>
      <div className="sheet conv-files" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grip" />
        <div className="conv-files-head"><b>Fichiers · {title}</b><button className="icon-btn" aria-label="Fermer" onClick={onClose}><I.Close size={20} /></button></div>
        {err && <p className="error">{err}</p>}
        {!msgs && !err && <p className="hint">Chargement…</p>}
        {msgs && !got.length && !made.length && <p className="hint">Aucun fichier dans cette conversation.</p>}
        {got.length > 0 && (<><h4>Reçus ({got.length})</h4><AttachRow items={got} /></>)}
        {made.length > 0 && (
          <>
            <h4>Créés par UniC ({made.length})</h4>
            {made.map((f) => f.url
              ? <div className="conv-file" key={f.id}><span>{f.filename}</span><ShareButton url={f.url} filename={f.filename} label="Ouvrir" /></div>
              : <FileCard key={f.id} id={f.id} filename={f.filename} mime={f.mime || ""} size={f.size} />)}
          </>
        )}
      </div>
    </div>
  );
}
