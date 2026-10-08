import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";

/**
 * Chantiers : une bannière par devis accepté, créée toute seule par le suivi des encaissements.
 * L'avancement affiché = le pourcentage déjà encaissé (argent seulement : ni photos, ni suivi de terrain).
 */
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/ | /g, " ");
const pct = (n: number) => `${String(n ?? 0).replace(".", ",")} %`;

export function Chantiers() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [open, setOpen] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api.tracking().then((d) => setRows(d.chantiers || [])).catch((e) => setErr(e?.message || "Erreur")); }, []);
  const running = (rows || []).filter((r) => !r.termine);
  const done = (rows || []).filter((r) => r.termine);
  const banner = (r: any) => {
    const isOpen = open === r.id;
    return (
      <article key={r.id} className={`cb ${r.termine ? "done" : ""} ${isOpen ? "open" : ""}`}>
        <button className="cb-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? "" : r.id)}>
          <span className="cb-title">{r.client}{r.lieu ? ` · ${r.lieu}` : ""}</span>
          <span className="cb-chev" aria-hidden="true">{isOpen ? "▴" : "▾"}</span>
          <span className="cb-bar" role="img" aria-label={`Avancement ${pct(r.avancement)}`}><i style={{ width: `${Math.min(100, r.avancement)}%` }} /></span>
          <span className="cb-sub">{r.termine ? "Terminé · soldé" : "En cours"} · {pct(r.avancement)}</span>
        </button>
        {isOpen && (
          <div className="cb-body">
            {r.titre && <p>{r.titre}</p>}
            <div className="cb-grid">
              <span>Devis</span><b><Link to={`/devis/${r.id}`}>{r.numero}</Link></b>
              <span>Montant</span><b>{money(r.montant)} {r.devise}</b>
              <span>Déjà reçu</span><b>{money(r.recu)} {r.devise}</b>
              <span>Reste</span><b>{money(r.reste)} {r.devise}</b>
            </div>
            <p className="hint">L'avancement suit les encaissements : à chaque paiement enregistré, la bannière avance.</p>
            <Link className="btn btn-copper btn-small" to={`/suivi/${encodeURIComponent(r.key)}`}>Ouvrir le dossier du client</Link>
          </div>
        )}
      </article>
    );
  };
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Chantiers</h1>
        <p className="lede">Un chantier apparaît tout seul dès qu'un devis est accepté dans le suivi des encaissements. Son avancement suit l'argent reçu.</p>
        {err && <p className="error">{err}</p>}
        {!rows && !err && <p className="hint">Chargement…</p>}
        {rows && !rows.length && <p className="hint">Aucun devis accepté pour l'instant. Marque un devis « Accepté » dans le suivi des encaissements : son chantier arrive ici.</p>}
        {running.length > 0 && <><h3 className="cb-h">En cours · {running.length}</h3>{running.map(banner)}</>}
        {done.length > 0 && <><h3 className="cb-h">Terminés · {done.length}</h3>{done.map(banner)}</>}
        <p className="hint"><Link to="/chantiers/manuels">Chantiers créés à la main</Link></p>
      </div>
    </div>
  );
}
