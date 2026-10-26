import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";

/**
 * Trésorerie prévisionnelle : l'argent qu'il y aura, semaine par semaine sur 90 jours, en deux scénarios (prudent / probable),
 * à partir du solde donné par le patron. Calculée par le serveur, sans IA. Alerte quand le prudent passe sous le seuil.
 */
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/[  ]/g, " ");
const short = (n: number) => (Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(1).replace(".", ",")} M` : Math.abs(n) >= 1e3 ? `${Math.round(n / 1e3)} k` : `${Math.round(n)}`);
const dm = (iso: string) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "");
const num = (v: string) => Number(String(v).replace(/[\s  ]/g, "").replace(",", "."));

function Curve({ weeks, seuil }: { weeks: any[]; seuil: number }) {
  const W = 640, H = 300, L = 58, R = 10, T = 12, B = 28;
  const vals = weeks.flatMap((w) => [w.solde_prudent, w.solde_probable]).concat([0, seuil]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, weeks.length - 1);
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / (hi - lo);
  const line = (k: string) => weeks.map((w, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(w[k]).toFixed(1)}`).join(" ");
  const ticks = [hi - pad, (hi + lo) / 2, lo + pad];
  const label = weeks.map((w) => `semaine du ${dm(w.du)} : prudent ${money(w.solde_prudent)}, probable ${money(w.solde_probable)}`).join(" ; ");
  return (
    <svg className="tr-curve" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Solde prévu. ${label}`}>
      {ticks.map((t, i) => (
        <g key={i}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="tr-grid" /><text x={L - 6} y={y(t) + 4} textAnchor="end" className="tr-tick">{short(t)}</text></g>
      ))}
      <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} className="tr-zero" />
      {seuil !== 0 && <line x1={L} x2={W - R} y1={y(seuil)} y2={y(seuil)} className="tr-seuil" />}
      <path d={line("solde_probable")} className="tr-prob" />
      <path d={line("solde_prudent")} className="tr-prud" />
      {weeks.map((w, i) => (i % 2 === 0 ? (
        <text key={w.du} x={x(i)} y={H - 8} textAnchor={i === 0 ? "start" : i === weeks.length - 1 ? "end" : "middle"} className="tr-tick">{dm(w.du)}</text>
      ) : null))}
      {weeks.map((w, i) => w.solde_prudent < seuil ? <circle key={`c${i}`} cx={x(i)} cy={y(w.solde_prudent)} r={3.5} className="tr-gap" /> : null)}
    </svg>
  );
}

export function Tresorerie() {
  const [f, setF] = useState<any>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [solde, setSolde] = useState("");
  const [charges, setCharges] = useState<any[]>([]);
  const [seuil, setSeuil] = useState("0");
  const [busy, setBusy] = useState(false);
  const fill = (d: any) => { setF(d); setCharges(d.charges || []); setSeuil(String(d.seuil ?? 0)); };
  useEffect(() => { api.tresorerie().then(fill).catch((e) => setErr(e?.message || "Erreur")); }, []);
  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true); setErr(""); setMsg("");
    try { fill(await fn()); setMsg(ok); return true; } catch (e: any) { setErr(e?.message || "Erreur"); return false; } finally { setBusy(false); }
  };
  const okSolde = solde.trim() !== "" && Number.isFinite(num(solde));
  const okCharges = charges.every((c) => String(c.libelle || "").trim() && Number.isFinite(num(String(c.montant))) && num(String(c.montant)) >= 0 && c.jour >= 1 && c.jour <= 31);
  const gap = f?.premier_trou;
  return (
    <div className="page">
      <div className="page-inner sv">
        <div className="an-tabs"><Link to="/analyse">Bilan</Link><span aria-current="page">Trésorerie</span></div>
        <h1>Trésorerie</h1>
        <p className="lede">L'argent que tu auras, semaine par semaine sur 90 jours. Calculé sans IA, en deux scénarios : prudent et probable.</p>
        {err && <p className="error" role="alert">{err}</p>}
        {!f && !err && <p className="hint">Calcul…</p>}
        {f && (
          <>
            <section className="card-box tr-solde">
              <div>
                <span className="sv-muted">Solde aujourd'hui</span>
                <b className={f.solde && f.solde.aujourdhui < 0 ? "neg" : ""}>{f.solde ? `${money(f.solde.aujourdhui)} FCFA` : "non donné"}</b>
                {f.solde && <small className="sv-muted">Donné le {dm(f.solde.donne_le)} : {money(f.solde.donne)} · entré depuis {money(f.solde.entrees_depuis)} · sorti {money(f.solde.sorties_depuis)}</small>}
              </div>
              <div className="tr-row">
                <input inputMode="decimal" value={solde} onChange={(e) => setSolde(e.target.value)} placeholder="Solde actuel (FCFA)" aria-label="Solde actuel en FCFA : caisse + banque + Wave" />
                <button className="btn btn-copper btn-small" disabled={busy || !okSolde}
                  onClick={() => run(() => api.tresorerieSolde(num(solde)), "Solde enregistré.").then((done) => done && setSolde(""))}>Mettre à jour</button>
              </div>
            </section>
            {gap ? (
              <p className="tr-alert" role="alert">⚠️ Semaine du {dm(gap.semaine_du)} (dans {gap.dans_jours} jours) : solde prudent de {money(gap.solde)} FCFA, sous ton seuil de {money(f.seuil)} FCFA.</p>
            ) : f.solde ? <p className="tr-ok">Pas de trou prévu sous ton seuil dans les {f.horizon_jours} jours (prudent).</p> : null}
            <div className="sv-kpis">
              <div className={`sv-kpi ${f.plus_bas.prudent.solde < f.seuil ? "warn" : ""}`}><span>Plus bas · prudent</span><b>{money(f.plus_bas.prudent.solde)} FCFA</b><small className="an-ev">semaine du {dm(f.plus_bas.prudent.semaine_du)}</small></div>
              <div className="sv-kpi"><span>Plus bas · probable</span><b>{money(f.plus_bas.probable.solde)} FCFA</b><small className="an-ev">semaine du {dm(f.plus_bas.probable.semaine_du)}</small></div>
              <div className="sv-kpi"><span>Fin · prudent</span><b>{money(f.semaines[f.semaines.length - 1]?.solde_prudent)} FCFA</b></div>
              <div className="sv-kpi"><span>Fin · probable</span><b>{money(f.semaines[f.semaines.length - 1]?.solde_probable)} FCFA</b></div>
            </div>
            <section className="card-box an-chart">
              <div className="an-legend"><span className="prud">Prudent</span><span className="prob">Probable</span>{f.seuil !== 0 && <span className="seu">Seuil</span>}</div>
              <Curve weeks={f.semaines} seuil={f.seuil} />
            </section>
            {f.points_attention.length > 0 && (
              <section className="card-box an-alerts"><h3 className="cb-h">Points d'attention</h3>
                <ul>{f.points_attention.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul></section>
            )}
            <h2 className="sv-h2">Argent attendu</h2>
            {f.entrees.length === 0 ? <p className="hint">Aucun reste à encaisser sur les devis acceptés.</p> : (
              <ul className="cb-exp-list an-sites">
                {f.entrees.map((r: any) => (
                  <li key={r.numero} className={r.etat === "en retard" ? "alert" : ""}>
                    <span><b>{r.client}</b><small> · {r.numero} · {r.date ? dm(r.date) : "sans date"} · {r.etat}</small></span>
                    <b>{money(r.montant)}</b>
                  </li>
                ))}
              </ul>
            )}
            <h2 className="sv-h2">Charges fixes du mois</h2>
            <div className="tr-charges">
              {charges.map((c, i) => (
                <div key={i} className="tr-charge">
                  <input value={c.libelle} maxLength={80} placeholder="Loyer, salaire, abonnement…" aria-label="Libellé de la charge"
                    onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, libelle: e.target.value } : x)))} />
                  <input inputMode="decimal" value={c.montant} aria-label="Montant FCFA"
                    onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, montant: e.target.value } : x)))} />
                  <label>le <input type="number" min={1} max={31} value={c.jour} aria-label="Jour du mois"
                    onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, jour: Number(e.target.value) } : x)))} /></label>
                  <button className="btn btn-line btn-small" aria-label={`Retirer ${c.libelle || "cette charge"}`} onClick={() => setCharges(charges.filter((_, j) => j !== i))}>×</button>
                </div>
              ))}
              <div className="tr-row">
                <button className="btn btn-line btn-small" disabled={charges.length >= 30} onClick={() => setCharges([...charges, { libelle: "", montant: "", jour: 1 }])}>+ Ajouter une charge</button>
                <label className="tr-seuil-in">Alerte sous <input inputMode="decimal" value={seuil} onChange={(e) => setSeuil(e.target.value)} aria-label="Seuil d'alerte FCFA" /> FCFA</label>
                <button className="btn btn-copper btn-small" disabled={busy || !okCharges || !Number.isFinite(num(seuil))}
                  onClick={() => run(() => api.tresorerieReglages(charges.map((c) => ({ libelle: String(c.libelle).trim(), montant: num(String(c.montant)), jour: c.jour })), num(seuil)), "Charges et seuil enregistrés.")}>Enregistrer</button>
              </div>
            </div>
            {msg && <p className="hint" role="status">{msg}</p>}
            <p className="hint">{f.note} Paie due aux ouvriers : {money(f.sorties.ouvriers)} FCFA (comptée tout de suite).</p>
          </>
        )}
      </div>
    </div>
  );
}
