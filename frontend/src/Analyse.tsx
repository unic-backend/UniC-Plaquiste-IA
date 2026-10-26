import { useEffect, useState } from "react";
import { api, downloadAuth } from "./api";

/**
 * Analyse & bilan : les vrais chiffres de l'entreprise sur une période, comparés à la période d'avant (calculés par le serveur,
 * sans IA) : encaissé, signé, dépenses, résultat, mois par mois, meilleurs clients, marges des chantiers, points d'attention.
 */
const PERIODES: [string, string][] = [
  ["ce_mois", "Ce mois"], ["mois_dernier", "Mois dernier"], ["3_mois", "3 mois"],
  ["cette_annee", "Cette année"], ["annee_derniere", "Année dernière"], ["12_mois", "12 mois"],
];
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/[  ]/g, " ");
const short = (n: number) => (Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(1).replace(".", ",")} M` : Math.abs(n) >= 1e3 ? `${Math.round(n / 1e3)} k` : `${Math.round(n)}`);
const fr = (iso: string) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "");

function Tile({ label, c, devise, better = "up", pct = false }: { label: string; c: any; devise: string; better?: "up" | "down"; pct?: boolean }) {
  const ev = c?.evolution_pct;
  const good = ev == null || ev === 0 ? "" : (ev > 0) === (better === "up") ? "ok" : "warn";
  const value = c?.valeur == null ? "—" : pct ? `${String(c.valeur).replace(".", ",")} %` : `${money(c.valeur)} ${devise}`;
  return (
    <div className={`sv-kpi ${label === "Résultat" && c?.valeur < 0 ? "warn" : ""}`}>
      <span>{label}</span>
      <b>{value}</b>
      {ev != null && <small className={`an-ev ${good}`}>{ev > 0 ? "▲" : ev < 0 ? "▼" : "="} {Math.abs(ev).toString().replace(".", ",")} % vs avant</small>}
      {ev == null && c?.avant != null && !pct && <small className="an-ev">avant : {money(c.avant)}</small>}
    </div>
  );
}

function Months({ rows, devise }: { rows: any[]; devise: string }) {
  const max = Math.max(1, ...rows.flatMap((m) => [m.encaisse, m.signe, m.depenses]));
  const summary = rows.map((m) => `${m.label} : encaissé ${money(m.encaisse)}, signé ${money(m.signe)}, dépenses ${money(m.depenses)} ${devise}`).join(" ; ");
  return (
    <section className="card-box an-chart">
      <div className="an-legend"><span className="enc">Encaissé</span><span className="sig">Signé</span><span className="dep">Dépenses</span></div>
      <div className="an-bars" role="img" aria-label={`Mois par mois. ${summary}`}>
        {rows.map((m) => (
          <div key={m.mois} className="an-month">
            <div className="an-trio">
              {(["encaisse", "signe", "depenses"] as const).map((k) => (
                <i key={k} className={k} style={{ height: `${Math.max(m[k] > 0 ? 2 : 0, (100 * m[k]) / max)}%` }} title={`${m.label} · ${money(m[k])} ${devise}`} />
              ))}
            </div>
            <small>{m.label.split(" ")[0]}</small>
          </div>
        ))}
      </div>
      <p className="hint">Échelle : la plus haute barre vaut {short(max)} {devise}.</p>
    </section>
  );
}

export function Analyse() {
  const [periode, setPeriode] = useState("ce_mois");
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setErr("");
    api.analyse(periode).then((d) => alive && setR(d)).catch((e) => alive && setErr(e?.message || "Erreur"));
    return () => { alive = false; };
  }, [periode]);
  const pdf = async () => {
    setBusy(true); setErr("");
    try { const a = await api.analysePdf(periode); await downloadAuth(a.download_url, a.filename); }
    catch (e: any) { setErr(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  const d = r?.devise || "FCFA";
  const ch = r?.chiffres || {};
  return (
    <div className="page">
      <div className="page-inner sv">
        <h1>Analyse & bilan</h1>
        <p className="lede">Tes vrais chiffres, calculés sur la base UniC (sans IA), comparés à la période d'avant. Demande aussi à l'IA : « fais-moi le bilan du mois ».</p>
        <div className="an-periods" role="tablist" aria-label="Période">
          {PERIODES.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={periode === k} className={`chip ${periode === k ? "on" : ""}`} onClick={() => setPeriode(k)}>{label}</button>
          ))}
        </div>
        {err && <p className="error" role="alert">{err}</p>}
        {!r && !err && <p className="hint">Calcul…</p>}
        {r && (
          <>
            <div className="sv-row">
              <p className="sv-muted">Du {fr(r.periode.du)} au {fr(r.periode.au)}{r.comparaison ? ` · comparé ${r.comparaison.label}` : ""}</p>
              <button className="btn btn-line btn-small" disabled={busy} onClick={pdf}>{busy ? "Préparation…" : "Rapport PDF"}</button>
            </div>
            {r.vide && <p className="hint">Aucun mouvement sur cette période : rien n'a été encaissé, signé ni dépensé.</p>}
            <div className="sv-kpis">
              <Tile label="Encaissé" c={ch.encaisse} devise={d} />
              <Tile label="Devis signés" c={ch.signe} devise={d} />
              <Tile label="Dépenses" c={ch.depenses} devise={d} better="down" />
              <Tile label="Résultat" c={ch.resultat} devise={d} />
              <Tile label="Devis acceptés" c={ch.taux_acceptation} devise={d} pct />
            </div>
            {r.points_attention.length > 0 && (
              <section className="card-box an-alerts" aria-label="Points d'attention">
                <h3 className="cb-h">Points d'attention</h3>
                <ul>{r.points_attention.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
              </section>
            )}
            <h2 className="sv-h2">Mois par mois</h2>
            <Months rows={r.par_mois} devise={d} />
            {r.clients.top.length > 0 && (
              <>
                <h2 className="sv-h2">Meilleurs clients (encaissé)</h2>
                <ul className="an-share">
                  {r.clients.top.map((c: any) => (
                    <li key={c.client}><span>{c.client}</span><b>{money(c.encaisse)} {d}</b>
                      <div className="sv-bar" aria-hidden><i style={{ width: `${c.part_pct || 0}%` }} /></div></li>
                  ))}
                </ul>
              </>
            )}
            {r.depenses_par_categorie.length > 0 && (
              <>
                <h2 className="sv-h2">Dépenses par catégorie</h2>
                <ul className="an-share">
                  {r.depenses_par_categorie.map((c: any) => (
                    <li key={c.categorie}><span>{c.categorie}</span><b>{money(c.montant)} {d}</b>
                      <div className="sv-bar an-dep" aria-hidden><i style={{ width: `${c.part_pct || 0}%` }} /></div></li>
                  ))}
                </ul>
              </>
            )}
            {r.chantiers.length > 0 && (
              <>
                <h2 className="sv-h2">Chantiers</h2>
                <ul className="cb-exp-list an-sites">
                  {r.chantiers.map((s: any) => (
                    <li key={s.numero} className={s.alerte ? "alert" : ""}>
                      <span><b>{s.numero}</b> · {s.client}<small> · {money(s.montant)} {d}{s.sans_depense ? " · aucune dépense saisie" : ` · dépenses ${money(s.depenses)}`}</small></span>
                      {!s.sans_depense && <b className={s.alerte ? "warn" : ""}>{s.marge_pct != null ? `${String(s.marge_pct).replace(".", ",")} %` : "—"}</b>}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <h2 className="sv-h2">Argent dû aujourd'hui</h2>
            <div className="sv-kpis">
              <div className="sv-kpi"><span>Reste à encaisser</span><b>{money(r.a_encaisser.reste)} {d}</b></div>
              <div className={`sv-kpi ${r.a_encaisser.plus_de_60_jours > 0 ? "warn" : ""}`}><span>Dû depuis + de 60 jours</span><b>{money(r.a_encaisser.plus_de_60_jours)} {d}</b></div>
            </div>
            <p className="hint">{r.note}</p>
          </>
        )}
      </div>
    </div>
  );
}
