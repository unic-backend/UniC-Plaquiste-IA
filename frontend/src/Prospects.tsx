import { useEffect, useState } from "react";
import { api, apiUrl } from "./api";

type Lead = { id: string; name: string; phone: string; area: string; need: string; surface: string; status: string; created_at: string };
const LABEL: Record<string, string> = { new: "À rappeler", contacted: "Contacté", done: "Terminé" };

/** Prospects laissés par les visiteurs du site + ligne à ajouter au site pour afficher la bulle de discussion. */
export function Prospects() {
  const [rows, setRows] = useState<Lead[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => api.leads().then(setRows).catch((e) => setMsg(e?.message || "Erreur"));
  useEffect(() => { load(); }, []);
  const origin = apiUrl("/").replace(/\/$/, "") || window.location.origin;
  const snippet = `<script src="${origin}/api/public/widget.js" defer></script>`;
  const wa = (p: string) => `https://wa.me/${p.replace(/\D/g, "").replace(/^(?!221)(\d{9})$/, "221$1")}`;
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Prospects du site</h1>
        <p className="lede">Les visiteurs de unicplaquiste.com discutent avec l'assistant du site. Leurs demandes arrivent ici, dans le briefing et par e-mail.</p>
        {msg && <p className="error">{msg}</p>}
        {!rows.length && <p className="hint">Aucun prospect pour l'instant.</p>}
        {rows.map((l) => (
          <article key={l.id} className={`card-box lead ${l.status}`}>
            <div className="lead-head"><b>{l.name}</b><span className="badge">{LABEL[l.status] || l.status}</span></div>
            <p className="hint">{new Date(l.created_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}{l.area ? ` · ${l.area}` : ""}{l.surface ? ` · ${l.surface}` : ""}</p>
            {l.need && <p>{l.need}</p>}
            <div className="row-actions">
              <a className="btn btn-copper btn-small" href={`tel:${l.phone}`}>Appeler {l.phone}</a>
              <a className="btn btn-line btn-small" href={wa(l.phone)} target="_blank" rel="noreferrer">WhatsApp</a>
              {l.status === "new" && <button className="btn btn-line btn-small" onClick={() => api.updateLead(l.id, "contacted").then(load)}>Contacté</button>}
              {l.status !== "done" && <button className="btn btn-line btn-small" onClick={() => api.updateLead(l.id, "done").then(load)}>Terminé</button>}
            </div>
          </article>
        ))}
        <section className="card-box install">
          <h2>Installer la bulle sur le site</h2>
          <p className="hint">Ajoute cette ligne juste avant <code>&lt;/body&gt;</code> sur les pages du site. Rien n'est publié tant que tu ne l'ajoutes pas.</p>
          <pre className="snippet">{snippet}</pre>
          <button className="btn btn-line btn-small" onClick={() => navigator.clipboard.writeText(snippet).then(() => setMsg("Ligne copiée."))}>Copier la ligne</button>
          <p className="hint">Limites : 30 messages par visiteur, 60 par jour et par appareil, 400 par jour au total (≈ 4 $ maximum). Au-delà, le visiteur est renvoyé vers WhatsApp.</p>
        </section>
      </div>
    </div>
  );
}
