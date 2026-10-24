import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/**
 * Équipe et paie : chaque ouvrier, ce qu'il a fait (journées ou tâches), ce qu'il a reçu (avances, paies) et ce qui lui reste dû.
 * Une journée notée sur un chantier compte aussi en main-d'œuvre de ce chantier (rentabilité). L'appli ne paie rien : on note.
 */
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/ | /g, " ");
const today = () => new Date().toISOString().slice(0, 10);

function Ouvrier({ id, chantiers, onChange }: { id: string; chantiers: any[]; onChange: () => void }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  const [w, setW] = useState({ days: "1", amount: "", label: "", quote_id: "", day: today() });
  const [p, setP] = useState({ amount: "", kind: "avance", method: "espèces" });
  const load = useCallback(() => api.teamWorker(id).then(setD).catch((e) => setErr(e?.message || "Erreur")), [id]);
  useEffect(() => { load(); }, [load]);
  const num = (v: string) => Number(v.replace(/\s/g, "").replace(",", "."));
  const run = async (fn: () => Promise<any>) => {
    setErr("");
    try { setD(await fn()); onChange(); } catch (e: any) { setErr(e?.message || "Erreur"); }
  };
  if (!d) return err ? <p className="error">{err}</p> : <p className="hint">Chargement…</p>;
  const task = d.mode === "tache" || !d.tarif_jour;
  return (
    <div className="cb-body">
      <div className="cb-grid">
        <span>Tarif</span><b>{d.tarif_jour ? `${money(d.tarif_jour)} / jour` : "à la tâche"}</b>
        <span>Travail noté</span><b>{money(d.travail)}{d.journees ? ` · ${String(d.journees).replace(".", ",")} j` : ""}</b>
        <span>Avances</span><b>{money(d.avances)}</b>
        <span>Payé</span><b>{money(d.paye)}</b>
        <span>Reste dû</span><b className={d.reste_du < 0 ? "error" : ""}>{money(d.reste_du)}{d.reste_du < 0 ? " (avance à récupérer)" : ""}</b>
      </div>
      <fieldset className="team-form">
        <legend>Travail fait</legend>
        {!task && <input inputMode="decimal" value={w.days} onChange={(e) => setW({ ...w, days: e.target.value })} aria-label="Nombre de journées" placeholder="Journées (1, 0,5…)" />}
        <input inputMode="decimal" value={w.amount} onChange={(e) => setW({ ...w, amount: e.target.value })} aria-label="Montant de la tâche"
          placeholder={task ? "Montant de la tâche" : "ou montant d'une tâche"} />
        <input value={w.label} onChange={(e) => setW({ ...w, label: e.target.value })} maxLength={200} aria-label="Travail" placeholder="Travail (ex. pose plafond salon)" />
        <select value={w.quote_id} onChange={(e) => setW({ ...w, quote_id: e.target.value })} aria-label="Chantier">
          <option value="">Sans chantier</option>
          {chantiers.map((c) => <option key={c.id} value={c.id}>{c.client}{c.lieu ? ` · ${c.lieu}` : ""} ({c.numero})</option>)}
        </select>
        <input type="date" value={w.day} onChange={(e) => setW({ ...w, day: e.target.value })} aria-label="Date" />
        <button className="btn btn-copper btn-small" disabled={task ? !(num(w.amount) > 0) : !(num(w.days) > 0 || num(w.amount) > 0)}
          onClick={() => run(() => api.teamWork(id, { days: !task && w.days ? num(w.days) : null, amount: w.amount ? num(w.amount) : null,
            label: w.label.trim(), quote_id: w.quote_id || null, day: w.day }))}>Noter le travail</button>
      </fieldset>
      <fieldset className="team-form">
        <legend>Argent remis</legend>
        <input inputMode="decimal" value={p.amount} onChange={(e) => setP({ ...p, amount: e.target.value })} aria-label="Montant remis" placeholder="Montant" />
        <select value={p.kind} onChange={(e) => setP({ ...p, kind: e.target.value })} aria-label="Type"><option value="avance">Avance</option><option value="paie">Paie</option></select>
        <select value={p.method} onChange={(e) => setP({ ...p, method: e.target.value })} aria-label="Moyen">
          {["espèces", "Wave", "Orange Money", "virement"].map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button className="btn btn-copper btn-small" disabled={!(num(p.amount) > 0)}
          onClick={() => run(async () => { const r = await api.teamPay(id, { amount: num(p.amount), kind: p.kind, method: p.method }); setP({ ...p, amount: "" }); return r; })}>Noter l'argent remis</button>
      </fieldset>
      {err && <p className="error">{err}</p>}
      {d.historique?.length > 0 && (
        <ul className="cb-exp-list">
          {d.historique.slice(0, 30).map((h: any) => (
            <li key={h.id} className={h.annule ? "off" : ""}>
              <span>{h.date} · {h.sorte === "travail" ? h.libelle : h.sorte === "avance" ? "Avance" : "Paie"}{h.chantier ? ` · ${h.chantier}` : ""}{h.sorte !== "travail" && h.libelle ? ` (${h.libelle})` : ""}</span>
              <b>{h.sorte === "travail" ? "" : "− "}{money(h.montant)}</b>
              {!h.annule && <button className="btn btn-line btn-small" aria-label="Annuler cette ligne"
                onClick={() => window.confirm("Annuler cette ligne ? Elle reste dans le journal mais ne compte plus.") && run(() => api.teamCancel(h.id))}>Annuler</button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Equipe() {
  const [d, setD] = useState<any>(null);
  const [chantiers, setChantiers] = useState<any[]>([]);
  const [open, setOpen] = useState("");
  const [msg, setMsg] = useState("");
  const [f, setF] = useState({ name: "", pay_mode: "jour", day_rate: "", role: "", phone: "" });
  const load = useCallback(() => api.team().then(setD).catch((e) => setMsg(e?.message || "Erreur")), []);
  useEffect(() => {
    load();
    api.tracking().then((t) => setChantiers((t.chantiers || []).filter((c: any) => !c.termine))).catch(() => {});
  }, [load]);
  const add = async () => {
    setMsg("");
    try {
      const rate = Number(f.day_rate.replace(/\s/g, "").replace(",", "."));
      await api.teamAddWorker({ ...f, name: f.name.trim(), day_rate: f.pay_mode === "jour" && rate > 0 ? rate : null });
      setF({ name: "", pay_mode: "jour", day_rate: "", role: "", phone: "" }); setMsg("Ouvrier ajouté."); load();
    } catch (e: any) { setMsg(e?.message || "Erreur"); }
  };
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Équipe</h1>
        <p className="lede">Journées, tâches, avances et paie de chaque ouvrier. Une journée sur un chantier compte dans sa main-d'œuvre.
          Ou dis-le au chat : « Moussa a travaillé 2 jours chez Diop », « j'ai donné 10 000 d'avance à Moussa ».</p>
        {d && <p className="hint">Reste dû à l'équipe : <b>{money(d.reste_du_total)} FCFA</b></p>}
        {msg && <p className="hint" role="status">{msg}</p>}
        {(d?.ouvriers || []).map((o: any) => (
          <article key={o.id} className={`cb ${open === o.id ? "open" : ""}`}>
            <button className="cb-head" aria-expanded={open === o.id} onClick={() => setOpen(open === o.id ? "" : o.id)}>
              <span className="cb-title">{o.nom}{o.role ? ` · ${o.role}` : ""}</span>
              <span className="cb-chev" aria-hidden="true">{open === o.id ? "▴" : "▾"}</span>
              <span className="cb-sub">Reste dû {money(o.reste_du)} FCFA</span>
            </button>
            {open === o.id && <Ouvrier id={o.id} chantiers={chantiers} onChange={load} />}
          </article>
        ))}
        {d && !d.ouvriers.length && <p className="hint">Aucun ouvrier pour l'instant : ajoute le premier ci-dessous.</p>}
        <section className="card-box team-new">
          <b>Ajouter un ouvrier</b>
          <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} maxLength={255} aria-label="Nom" placeholder="Nom (ex. Moussa Ndiaye)" />
          <select value={f.pay_mode} onChange={(e) => setF({ ...f, pay_mode: e.target.value })} aria-label="Mode de paie">
            <option value="jour">Payé à la journée</option><option value="tache">Payé à la tâche</option>
          </select>
          {f.pay_mode === "jour" && <input inputMode="decimal" value={f.day_rate} onChange={(e) => setF({ ...f, day_rate: e.target.value })} aria-label="Tarif du jour" placeholder="Tarif du jour (FCFA)" />}
          <input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} maxLength={64} aria-label="Métier" placeholder="Métier (plaquiste, aide, peintre…)" />
          <input type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} maxLength={40} aria-label="Téléphone" placeholder="Téléphone" />
          <button className="btn btn-copper" disabled={f.name.trim().length < 2} onClick={add}>Ajouter</button>
        </section>
      </div>
    </div>
  );
}
