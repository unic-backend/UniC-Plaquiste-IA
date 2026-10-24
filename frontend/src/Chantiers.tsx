import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";

/**
 * Chantiers : une bannière par devis accepté, créée toute seule par le suivi des encaissements.
 * L'avancement affiché = le pourcentage déjà encaissé (argent seulement : ni photos, ni suivi de terrain).
 */
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/ | /g, " ");
const pct = (n: number) => `${String(n ?? 0).replace(".", ",")} %`;
const KINDS = ["matériaux", "main-d'œuvre", "transport", "location", "autre"];

/** Dépenses d'un chantier : ce qu'il a coûté, par catégorie (matériaux et main-d'œuvre séparés), et ce qu'il rapporte. */
function Depenses({ qid, devise, onChange }: { qid: string; devise: string; onChange: () => void }) {
  const [d, setD] = useState<any>(null);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [cat, setCat] = useState("matériaux");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.chantierExpenses(qid).then(setD).catch((e) => setErr(e?.message || "Erreur")), [qid]);
  useEffect(() => { load(); }, [load]);
  const n = Number(amount.replace(/\s/g, "").replace(",", "."));
  const add = async () => {
    setBusy(true); setErr("");
    try { setD(await api.addChantierExpense(qid, { label: label.trim(), amount: n, category: cat })); setLabel(""); setAmount(""); onChange(); }
    catch (e: any) { setErr(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  const cancel = async (id: string) => {
    if (!window.confirm("Annuler cette dépense ? Elle reste dans le journal mais ne compte plus.")) return;
    try { setD(await api.cancelChantierExpense(id)); onChange(); } catch (e: any) { setErr(e?.message || "Erreur"); }
  };
  if (!d) return err ? <p className="error">{err}</p> : <p className="hint">Chargement des dépenses…</p>;
  return (
    <div className="cb-exp">
      <div className="cb-grid">
        <span>Dépenses</span><b>{money(d.total)} {devise}</b>
        {Object.entries(d.par_categorie || {}).flatMap(([k, v]) => [
          <span key={k} className="cb-sub2">· {k}</span>, <b key={`${k}-v`} className="cb-sub2">{money(v as number)} {devise}</b>])}
        <span>Marge prévue</span><b className={d.marge_prevue < 0 ? "error" : ""}>{money(d.marge_prevue)} {devise} · {pct(d.marge_pct)}</b>
        <span>Marge encaissée</span><b className={d.marge_encaissee < 0 ? "error" : ""}>{money(d.marge_encaissee)} {devise}</b>
      </div>
      {d.lignes?.length > 0 && (
        <ul className="cb-exp-list">
          {d.lignes.map((l: any) => (
            <li key={l.id} className={l.annulee ? "off" : ""}>
              <span>{l.date} · {l.libelle} <small>({l.categorie})</small></span>
              <b>{money(l.montant)}</b>
              {!l.annulee && <button className="btn btn-line btn-small" aria-label={`Annuler la dépense ${l.libelle}`} onClick={() => cancel(l.id)}>Annuler</button>}
            </li>
          ))}
        </ul>
      )}
      <div className="cb-exp-form">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Ce qui a été payé (ex. 20 plaques BA13)" maxLength={255} aria-label="Libellé de la dépense" />
        <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder={`Montant (${devise})`} aria-label="Montant de la dépense" />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Catégorie">{KINDS.map((k) => <option key={k} value={k}>{k}</option>)}</select>
        <button className="btn btn-copper btn-small" disabled={busy || !label.trim() || !(n > 0)} onClick={add}>{busy ? "…" : "Ajouter la dépense"}</button>
      </div>
      {err && <p className="error">{err}</p>}
      <p className="hint">Tu peux aussi le dire au chat : « j'ai payé 150 000 de plaques pour le chantier de Diop ».</p>
    </div>
  );
}

export function Chantiers() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [open, setOpen] = useState("");
  const [err, setErr] = useState("");
  const reload = useCallback(() => { api.tracking().then((d) => setRows(d.chantiers || [])).catch((e) => setErr(e?.message || "Erreur")); }, []);
  useEffect(() => { reload(); }, [reload]);
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
          <span className="cb-sub">{r.termine ? "Terminé · soldé" : "En cours"} · {pct(r.avancement)}{r.depenses > 0 ? ` · marge ${pct(r.marge_pct)}` : ""}</span>
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
            <Depenses qid={r.id} devise={r.devise} onChange={reload} />
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
