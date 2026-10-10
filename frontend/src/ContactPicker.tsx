import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { isNative } from "./api";
import * as I from "./Icons";
import { fold, type Contact } from "./phoneMatch";

/**
 * Choisir un client dans les contacts du téléphone : remplit le nom et le numéro du formulaire.
 * Les contacts sont lus sur le téléphone et ne partent jamais au serveur (seul le contact choisi remplit le formulaire).
 */
type WebContacts = { select: (props: string[], o: { multiple: boolean }) => Promise<{ name?: string[]; tel?: string[] }[]> };
const webPicker = (): WebContacts | null => (typeof navigator !== "undefined" && (navigator as any).contacts?.select ? (navigator as any).contacts : null);

export const contactsAvailable = (): boolean => isNative || !!webPicker();

const digits = (s: string) => s.replace(/\D/g, "");

export function ContactButton({ onPick, label = "Contacts" }: { onPick: (c: Contact) => void; label?: string }) {
  const [open, setOpen] = useState(false);
  if (!contactsAvailable()) return null;
  const go = async () => {
    const web = !isNative ? webPicker() : null;
    if (web) {   // navigateur (Chrome Android) : sélecteur du système
      try {
        const [c] = await web.select(["name", "tel"], { multiple: false });
        if (c) onPick({ name: c.name?.[0] || "", number: c.tel?.[0] || "" });
      } catch { /* annulé */ }
      return;
    }
    setOpen(true);
  };
  return (
    <>
      <button type="button" className="contact-btn" onClick={go} aria-label="Choisir dans mes contacts">
        <I.User size={16} /> {label}
      </button>
      {open && createPortal(<ContactSheet onClose={() => setOpen(false)} onPick={(c) => { setOpen(false); onPick(c); }} />, document.body)}
    </>
  );
}

function ContactSheet({ onClose, onPick }: { onClose: () => void; onPick: (c: Contact) => void }) {
  const [all, setAll] = useState<Contact[] | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    import("./phone").then(({ phone }) => phone.listContacts()).then(setAll)
      .catch((e) => setErr(e?.message || "Contacts indisponibles."));
  }, []);
  const shown = useMemo(() => {
    if (!all) return [];
    const f = fold(q), d = digits(q);
    const hits = !q.trim() ? all : all.filter((c) => (f && fold(c.name).includes(f)) || (d.length >= 3 && digits(c.number).includes(d)));
    return hits.slice(0, 80);
  }, [all, q]);
  return (
    <div className="sheet-back" role="dialog" aria-label="Mes contacts" onClick={onClose}>
      <div className="sheet contact-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grip" />
        <div className="conv-files-head"><b>Mes contacts</b><button className="icon-btn" aria-label="Fermer" onClick={onClose}><I.Close size={20} /></button></div>
        <input className="sv-search" type="search" autoFocus placeholder="Nom ou numéro…" value={q} onChange={(e) => setQ(e.target.value)} />
        {err && <p className="error">{err}</p>}
        {!all && !err && <p className="hint">Lecture des contacts…</p>}
        {all && !shown.length && <p className="hint">Aucun contact trouvé.</p>}
        <div className="contact-list">
          {shown.map((c) => (
            <button key={c.name + c.number} className="contact-row" onClick={() => onPick(c)}>
              <span className="contact-av" aria-hidden>{(c.name.trim()[0] || "?").toUpperCase()}</span>
              <span className="contact-txt"><b>{c.name}</b><small>{c.number}</small></span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
