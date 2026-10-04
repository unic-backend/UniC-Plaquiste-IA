import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { fetchBlobUrl } from "./api";
import { pdfThumb } from "./compress";

/** Fichier joint : local (avant / juste après l'envoi) ou sur le serveur (conversation rechargée). */
export type Attach = { name: string; mime?: string; id?: string; file?: File };

const isPdf = (a: Attach) => /pdf/i.test(a.mime || a.file?.type || "") || /\.pdf$/i.test(a.name);
const isImage = (a: Attach) => /^image\//i.test(a.mime || a.file?.type || "") || /\.(jpe?g|png|webp|gif|heic)$/i.test(a.name);
const ext = (n: string) => (n.split(".").pop() || "FICHIER").toUpperCase().slice(0, 5);

// Aperçu calculé une seule fois par fichier local : la carte du champ de saisie et celle du message envoyé le partagent.
const localThumbs = new WeakMap<File, Promise<string | null>>();

function localThumb(a: Attach): Promise<string | null> {
  const f = a.file!;
  let p = localThumbs.get(f);
  if (!p) {
    p = isImage(a) ? Promise.resolve(URL.createObjectURL(f)) : isPdf(a) ? pdfThumb(f) : Promise.resolve(null);
    localThumbs.set(f, p);
  }
  return p;
}

/** Aperçu : photo telle quelle, 1re page d'un PDF ; null = pas d'aperçu (carte texte). */
function useThumb(a: Attach, size = 600): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null, live = true;
    if (a.file && size <= 600) {
      localThumb(a).then((u) => { if (live) setSrc(u); });
    } else if (a.file && isImage(a)) {
      url = URL.createObjectURL(a.file);
      setSrc(url);
    } else if (a.file && isPdf(a)) {
      pdfThumb(a.file, 1600).then((u) => { url = u; if (live) setSrc(u); });
    } else if (a.id && (isImage(a) || isPdf(a))) {
      fetchBlobUrl(`/api/files/${a.id}/thumb?size=${size}`).then((u) => { url = u; if (live) setSrc(u); }).catch(() => live && setSrc(null));
    }
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [a.id, a.file, size]);
  return src;
}

function Lightbox({ a, onClose }: { a: Attach; onClose: () => void }) {
  const src = useThumb(a, 1600);
  return createPortal(
    <div className="lightbox" role="dialog" aria-label={a.name} onClick={onClose}>
      {src ? <img src={src} alt={a.name} /> : <span className="hint">Chargement…</span>}
      <button className="lightbox-x" aria-label="Fermer" onClick={onClose}>×</button>
    </div>,
    document.body,
  );
}

export function AttachCard({ a, onRemove }: { a: Attach; onRemove?: () => void }) {
  const src = useThumb(a);
  const [open, setOpen] = useState(false);
  return (
    <div className={`attach ${src ? "has-thumb" : ""}`}>
      <button type="button" className="attach-body" onClick={() => src && setOpen(true)} aria-label={`Voir ${a.name}`}>
        {src ? <img src={src} alt={a.name} /> : (
          <span className="attach-doc"><span className="attach-ext">{isPdf(a) ? "PDF" : ext(a.name)}</span><span className="attach-name">{a.name}</span></span>
        )}
        {src && isPdf(a) && <span className="attach-tag">PDF</span>}
      </button>
      {onRemove && <button type="button" className="attach-x" aria-label={`Retirer ${a.name}`} onClick={onRemove}>×</button>}
      {open && <Lightbox a={a} onClose={() => setOpen(false)} />}
    </div>
  );
}

export function AttachRow({ items, onRemove, className = "" }: { items: Attach[]; onRemove?: (i: number) => void; className?: string }) {
  if (!items.length) return null;
  return (
    <div className={`attach-row ${className}`}>
      {items.map((a, i) => <AttachCard key={(a.id || a.name) + i} a={a} onRemove={onRemove ? () => onRemove(i) : undefined} />)}
    </div>
  );
}
