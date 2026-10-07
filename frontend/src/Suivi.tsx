import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "./api";

/**
 * Suivi des encaissements : l'argent des devis, client par client. Jamais l'avancement du chantier.
 * Les chiffres viennent du serveur (calculés en code). Rien n'est enregistré sans un clic du patron :
 * les e-mails ne font que suggérer.
 */
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/ | /g, " ");
const pct = (n: number) => `${String(n ?? 0).replace(".", ",")} %`;
const STATE_TONE: Record<string, string> = { "à encaisser": "warn", "en attente": "wait", "soldé": "ok", "refusé": "off" };
const DECISION_FR: Record<string, string> = { pending: "En attente", accepted: "Accepté", declined: "Refusé" };

function Bar({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value || 0));
  return <div className="sv-bar" role="img" aria-label={`${pct(v)} encaissé`}><i style={{ width: `${v}%` }} /></div>;
}

function Kpi({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return <div className={`sv-kpi ${tone}`}><span>{label}</span><b>{value}</b></div>;
}

function MailSuggestions({ onApplied }: { onApplied: () => void }) {
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = useCallback((refresh = false) => {
    setBusy(true); setMsg("");
    api.trackingMail(refresh).then((d) => { setRows(d.suggestions || []); if (d.note) setMsg(d.note); })
      .catch((e) => setMsg(e?.message || "Erreur")).finally(() => setBusy(false));
  }, []);
  useEffect(() => { load(); }, [load]);
  const apply = async (h: any) => {
    setMsg("");
    try {
      const q = h.devis_id;
      if (h.signal === "acceptation") await api.trackingDecide(q, "accepted");
      else await api.trackingReceipt({ quote_id: q, amount: h.montant, kind: "avance", mail_id: h.mail_id, note: `D'après un e-mail de ${h.de}` });
      if (h.signal === "acceptation") await api.trackingDismiss(h.mail_id);
      load(); onApplied();
    } catch (e: any) { setMsg(e?.message || "Erreur"); }
  };
  const skip = async (h: any) => { try { await api.trackingDismiss(h.mail_id); load(); } catch (e: any) { setMsg(e?.message || "Erreur"); } };
  return (
    <section className="card-box sv-mail">
      <div className="sv-row">
        <h3>Dans mes e-mails</h3>
        <button className="btn btn-line btn-small" disabled={busy} onClick={() => load(true)}>{busy ? "Lecture…" : "Lire mes mails"}</button>
      </div>
      {!rows.length && <p className="sv-muted">Aucun e-mail client à vérifier. Rien n'est enregistré sans toi.</p>}
      {rows.map((h) => (
        <div className="sv-hint" key={h.mail_id}>
          <div><b>{h.client}</b> <span className={`sv-chip ${h.signal === "paiement" ? "ok" : "wait"}`}>{h.signal === "paiement" ? "Paiement ?" : "Acceptation ?"}</span></div>
          <p className="sv-quote">« {h.extrait} »</p>
          <p className="sv-muted">{h.objet}{h.montant ? ` · ${money(h.montant)} FCFA détectés` : ""}</p>
          <div className="sv-actions">
            {h.devis && (h.signal === "acceptation" || h.montant) && (
              <button className="btn btn-copper btn-small" onClick={() => apply(h)}>
                {h.signal === "acceptation" ? `Marquer ${h.devis} accepté` : `Enregistrer ${money(h.montant)} FCFA`}
              </button>
            )}
            {!h.devis && h.devis_possibles?.length > 0 && <span className="sv-muted">Plusieurs devis : ouvre la fiche du client.</span>}
            <button className="btn btn-line btn-small" onClick={() => skip(h)}>Écarter</button>
          </div>
        </div>
      ))}
      {msg && <p className="error">{msg}</p>}
    </section>
  );
}

export function Suivi() {
  const nav = useNavigate();
  const [ov, setOv] = useState<any>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => { api.tracking().then(setOv).catch((e) => setErr(e?.message || "Erreur")); }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="page">
      <div className="page-inner sv">
        <h1>Suivi des encaissements</h1>
        <p className="lede">L'argent de tes devis, client par client. Dis dans le chat : « Awa a accepté » ou « j'ai reçu 300 000 d'Awa ».</p>
        {err && <p className="error">{err}</p>}
        {ov && (
          <>
            <section className="card-box sv-hero">
              <div className="sv-hero-top"><span>Encaissé sur les devis acceptés</span><b>{pct(ov.pct_recu)}</b></div>
              <Bar value={ov.pct_recu} />
              <div className="sv-kpis">
                <Kpi label="Devis acceptés" value={`${money(ov.accepte)} ${ov.devise}`} />
                <Kpi label="Déjà reçu" value={`${money(ov.recu)} ${ov.devise}`} tone="ok" />
                <Kpi label={`Reste à encaisser · ${pct(ov.pct_reste)}`} value={`${money(ov.reste)} ${ov.devise}`} tone="warn" />
                <Kpi label={`En attente de réponse · ${ov.nb_attente} devis`} value={`${money(ov.en_attente)} ${ov.devise}`} />
              </div>
            </section>
            <MailSuggestions onApplied={load} />
            <h2 className="sv-h2">Clients · {ov.nb_clients}</h2>
            {!ov.clients.length && <p className="sv-muted">Aucun devis pour l'instant. Crée un devis dans le chat : il apparaît ici tout seul.</p>}
            <div className="sv-list">
              {ov.clients.map((c: any) => (
                <button key={c.key} className="sv-client" onClick={() => nav(`/suivi/${encodeURIComponent(c.key)}`)}>
                  <div className="sv-row"><b>{c.client}</b><span className={`sv-chip ${STATE_TONE[c.etat]}`}>{c.etat}</span></div>
                  {c.accepte > 0 ? (
                    <>
                      <Bar value={c.pct_recu} />
                      <div className="sv-row sv-small"><span>Reçu {money(c.recu)} · {pct(c.pct_recu)}</span><span>Reste {money(c.reste)} · {pct(c.pct_reste)}</span></div>
                      <div className="sv-small sv-muted">Devis accepté {money(c.accepte)} {c.devise}</div>
                    </>
                  ) : (
                    <div className="sv-small sv-muted">{c.nb_attente} devis en attente · {money(c.en_attente)} {c.devise}</div>
                  )}
                </button>
              ))}
            </div>
          </>
        )}
        {!ov && !err && <p className="sv-muted">Chargement…</p>}
      </div>
    </div>
  );
}

function ReceiptForm({ quote, onDone }: { quote: any; onDone: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ amount: "", kind: "avance", received_on: today, method: "" });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const amount = Number(f.amount.replace(/\s/g, "").replace(",", "."));
  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await api.trackingReceipt({ quote_id: quote.id, amount, kind: f.kind, received_on: f.received_on, method: f.method });
      if (r.alerte) window.alert(r.alerte);
      onDone();
    } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  return (
    <div className="sv-form">
      <label>Montant reçu (FCFA)<input inputMode="numeric" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} placeholder="ex. 300 000" /></label>
      <div className="two-col">
        <label>Type<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {[["avance", "Avance"], ["acompte", "Acompte"], ["solde", "Solde"], ["autre", "Autre"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Date<input type="date" value={f.received_on} max={today} onChange={(e) => setF({ ...f, received_on: e.target.value })} /></label>
      </div>
      <label>Moyen (optionnel)<input value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })} placeholder="Wave, Orange Money, espèces, virement…" /></label>
      <button className="btn btn-copper" disabled={busy || !(amount > 0)} onClick={save}>Enregistrer le versement</button>
      {msg && <p className="error">{msg}</p>}
    </div>
  );
}

export function SuiviClient() {
  const { key = "" } = useParams();
  const nav = useNavigate();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState("");
  const load = useCallback(() => { api.trackingClient(key).then(setD).catch((e) => setErr(e?.message || "Erreur")); }, [key]);
  useEffect(() => { load(); }, [load]);
  const run = async (fn: () => Promise<any>) => { setErr(""); try { await fn(); setOpen(""); load(); } catch (e: any) { setErr(e?.message || "Erreur"); } };
  if (!d) return <div className="page"><div className="page-inner sv"><Link to="/suivi">← Suivi</Link>{err ? <p className="error">{err}</p> : <p className="sv-muted">Chargement…</p>}</div></div>;
  return (
    <div className="page">
      <div className="page-inner sv">
        <Link to="/suivi" className="sv-back">← Suivi des encaissements</Link>
        <h1>{d.client}</h1>
        <span className={`sv-chip ${STATE_TONE[d.etat]}`}>{d.etat}</span>
        {d.accepte > 0 && (
          <section className="card-box sv-hero">
            <div className="sv-hero-top"><span>Encaissé</span><b>{pct(d.pct_recu)}</b></div>
            <Bar value={d.pct_recu} />
            <div className="sv-kpis">
              <Kpi label="Devis accepté" value={`${money(d.accepte)} ${d.devise}`} />
              <Kpi label="Reçu" value={`${money(d.recu)} ${d.devise}`} tone="ok" />
              <Kpi label={`Reste · ${pct(d.pct_reste)}`} value={`${money(d.reste)} ${d.devise}`} tone="warn" />
            </div>
          </section>
        )}
        {err && <p className="error">{err}</p>}
        <h2 className="sv-h2">Devis</h2>
        {d.devis.map((q: any) => (
          <section className="card-box sv-quote-card" key={q.id}>
            <div className="sv-row"><b>{q.numero}</b><span className={`sv-chip ${q.decision === "accepted" ? "ok" : q.decision === "declined" ? "off" : "wait"}`}>{DECISION_FR[q.decision]}</span></div>
            <div className="sv-small sv-muted">{[q.titre, q.lieu].filter(Boolean).join(" · ")}{q.brouillon ? " · brouillon" : ""}</div>
            <div className="sv-row"><span>Montant du devis</span><b>{money(q.montant)} {q.devise}</b></div>
            {q.decision === "accepted" && (
              <>
                <Bar value={q.pct_recu} />
                <div className="sv-row sv-small"><span>Reçu {money(q.recu)} · {pct(q.pct_recu)}</span><span>Reste {money(q.reste)} · {pct(q.pct_reste)}</span></div>
              </>
            )}
            <div className="sv-seg" role="group" aria-label="Réponse du client">
              {(["pending", "accepted", "declined"] as const).map((v) => (
                <button key={v} className={q.decision === v ? "on" : ""} aria-pressed={q.decision === v}
                  onClick={() => q.decision !== v && run(() => api.trackingDecide(q.id, v))}>{DECISION_FR[v]}</button>
              ))}
            </div>
            {q.decision === "accepted" && (
              <div className="sv-actions">
                <button className="btn btn-copper btn-small" onClick={() => setOpen(open === q.id ? "" : q.id)}>{open === q.id ? "Fermer" : "J'ai reçu un paiement"}</button>
                {q.reste > 0 && !d.factures_solde.length && (
                  <button className="btn btn-line btn-small" onClick={() => run(async () => { const r = await api.trackingBalance(q.id); nav(`/factures/${r.id}`); })}>Facture de reliquat</button>
                )}
              </div>
            )}
            {open === q.id && <ReceiptForm quote={q} onDone={() => { setOpen(""); load(); }} />}
          </section>
        ))}
        {d.factures_solde.length > 0 && (
          <>
            <h2 className="sv-h2">Factures de reliquat</h2>
            {d.factures_solde.map((i: any) => (
              <Link key={i.id} className="sv-link" to={`/factures/${i.id}`}>{i.numero} · reste {money(i.reste)} FCFA · {i.statut === "draft" ? "brouillon à approuver" : i.statut}</Link>
            ))}
          </>
        )}
        <h2 className="sv-h2">Versements reçus</h2>
        {!d.versements.length && <p className="sv-muted">Aucun versement enregistré.</p>}
        {d.versements.map((v: any) => (
          <div className="sv-pay" key={v.id}>
            <div>
              <b>{money(v.montant)} FCFA</b> <span className="sv-muted">· {v.type}{v.moyen ? ` · ${v.moyen}` : ""}</span>
              <div className="sv-small sv-muted">{v.date ? new Date(v.date).toLocaleDateString("fr-FR") : ""} · {v.devis}{v.note ? ` · ${v.note}` : ""}</div>
            </div>
            <button className="btn btn-line btn-small" aria-label="Annuler ce versement"
              onClick={() => window.confirm(`Annuler le versement de ${money(v.montant)} FCFA ? (erreur de saisie)`) && run(() => api.trackingCancelReceipt(v.id))}>Annuler</button>
          </div>
        ))}
      </div>
    </div>
  );
}
