import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, isNative, shareText } from "./api";

/**
 * Suivi des encaissements : l'argent des devis, client par client. Jamais l'avancement du chantier.
 * Les chiffres viennent du serveur (calculés en code). Rien n'est enregistré sans un clic du patron :
 * les e-mails ne font que suggérer.
 */
const money = (n: number) => Math.round(n || 0).toLocaleString("fr-FR").replace(/ | /g, " ");
const pct = (n: number) => `${String(n ?? 0).replace(".", ",")} %`;
const STATE_TONE: Record<string, string> = { "à encaisser": "warn", "en attente": "wait", "soldé": "ok", "refusé": "off" };
const waLink = (phone: string) => {
  const d = phone.replace(/\D/g, "");
  return d ? `https://wa.me/${d.length === 9 && d.startsWith("7") ? "221" + d : d}` : "";   // numéro sénégalais sans indicatif : +221
};
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

const REMIND_BASE = 6000;   // identifiants des rappels d'encaissement : 6000 à 6199

/** Rappel local sur le téléphone, à 9 h le jour de chaque encaissement prévu (fonctionne hors connexion). */
async function scheduleCollectReminders(rows: any[]) {
  if (!isNative) return;
  try {
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    await LocalNotifications.cancel({ notifications: Array.from({ length: 200 }, (_, i) => ({ id: REMIND_BASE + i })) }).catch(() => {});
    const now = Date.now();
    const list = rows.map((r) => ({ r, at: new Date(`${r.date}T09:00:00`).getTime() })).filter((x) => x.at > now).slice(0, 200)
      .map((x, i) => ({ id: REMIND_BASE + i, title: "Encaissement à relancer", body: `${x.r.client} · reste ${money(x.r.reste)} ${x.r.devise}`,
        schedule: { at: new Date(x.at), allowWhileIdle: true } }));
    if (!list.length) return;
    const perm = await LocalNotifications.requestPermissions();
    if (perm.display === "granted") await LocalNotifications.schedule({ notifications: list });
  } catch { /* rappels indisponibles : le suivi reste utilisable */ }
}

/** Conversation avec UniC DANS le suivi : rien ne s'ouvre ailleurs, les chiffres de la page se mettent à jour après chaque réponse. */
function SuiviChat({ k, title, hint, onChanged }: { k: string; title: string; hint: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<{ id: string; role: string; content: string }[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const load = useCallback(() => api.trackingChat(k).then((d) => setMsgs(d.messages)).catch(() => {}), [k]);
  useEffect(() => { if (open) load(); }, [open, load]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);
  const send = async () => {
    const m = text.trim();
    if (!m || busy) return;
    setBusy(true); setErr(""); setText("");
    setMsgs((x) => [...x, { id: `tmp-${Date.now()}`, role: "user", content: m }]);
    try { await api.trackingSay(k, m); await load(); onChanged(); }
    catch (e: any) { setErr(e?.message || "Erreur"); await load(); }
    finally { setBusy(false); }
  };
  return (
    <section className="card-box sv-chat">
      <button className="sv-chat-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <b>{title}</b><span>{open ? "Réduire" : "Ouvrir"}</span>
      </button>
      {open && (
        <>
          <div className="sv-chat-log" role="log" aria-live="polite">
            {!msgs.length && <p className="sv-muted">{hint}</p>}
            {msgs.map((m) => <div key={m.id} className={`sv-msg ${m.role}`}>{m.content.replace(/\*\*/g, "")}</div>)}
            {busy && <div className="sv-msg assistant sv-typing">UniC réfléchit…</div>}
            <div ref={end} />
          </div>
          {err && <p className="error">{err}</p>}
          <div className="sv-chat-in">
            <textarea rows={1} value={text} placeholder="Écris ici…" onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button className="btn btn-copper btn-small" disabled={busy || !text.trim()} onClick={send}>Envoyer</button>
          </div>
        </>
      )}
    </section>
  );
}

const FILTERS: [string, string][] = [["actifs", "Actifs"], ["à encaisser", "À encaisser"], ["en attente", "En attente"], ["soldé", "Soldés"], ["refusé", "Refusés"]];

export function Suivi() {
  const nav = useNavigate();
  const [ov, setOv] = useState<any>(null);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("actifs");
  const [search, setSearch] = useState("");
  const load = useCallback(() => { api.tracking().then((d) => { setOv(d); scheduleCollectReminders(d.rappels || []); }).catch((e) => setErr(e?.message || "Erreur")); }, []);
  useEffect(() => { load(); }, [load]);
  const restore = async (id: string) => { try { await api.trackingRestore(id); load(); } catch (e: any) { setErr(e?.message || "Erreur"); } };
  const shown = (ov?.clients || []).filter((c: any) => (filter === "actifs" ? c.etat !== "refusé" : c.etat === filter)
    && (!search.trim() || c.client.toLowerCase().includes(search.trim().toLowerCase())));
  const open = (key: string) => nav(`/suivi/${encodeURIComponent(key)}`);
  return (
    <div className="page">
      <div className="page-inner sv">
        <h1>Suivi des encaissements</h1>
        <p className="lede">L'argent de tes devis, client par client. Tout se fait ici : parle à UniC en bas, ou touche un client.</p>
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
            {ov.rappels.length > 0 && (
              <section className="card-box sv-alert">
                <h3>🔔 Encaissements prévus</h3>
                {ov.rappels.map((r: any) => (
                  <button key={r.numero} className={`sv-line ${r.jours_retard ? "late" : ""}`} onClick={() => open(r.key)}>
                    <span><b>{r.client}</b> · {money(r.reste)} {r.devise}</span>
                    <span>{r.jours_retard ? `${r.jours_retard} j de retard` : r.dans_jours ? `dans ${r.dans_jours} j` : "aujourd'hui"}</span>
                  </button>
                ))}
              </section>
            )}
            {ov.sans_reponse.length > 0 && (
              <section className="card-box sv-alert">
                <h3>⏳ Sans réponse depuis 7 jours ou plus</h3>
                {ov.sans_reponse.map((r: any) => (
                  <button key={r.numero} className="sv-line" onClick={() => open(r.key)}>
                    <span><b>{r.client}</b> · {money(r.montant)} {r.devise}</span><span>{r.jours} j</span>
                  </button>
                ))}
              </section>
            )}
            <SuiviChat k="_all" title="💬 Parler à UniC" onChanged={load}
              hint="Ex. « Awa a accepté son devis », « j'ai reçu 300 000 de Moussa », « qui me doit le plus ? »" />
            <MailSuggestions onApplied={load} />
            <h2 className="sv-h2">Clients · {ov.nb_clients}</h2>
            <input className="sv-search" type="search" placeholder="Chercher un client…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="sv-filters" role="group" aria-label="Filtrer">
              {FILTERS.map(([v, l]) => <button key={v} className={filter === v ? "on" : ""} aria-pressed={filter === v} onClick={() => setFilter(v)}>{l}</button>)}
            </div>
            {!ov.clients.length && <p className="sv-muted">Aucun devis pour l'instant. Crée un devis dans le chat : il apparaît ici tout seul.</p>}
            {ov.clients.length > 0 && !shown.length && <p className="sv-muted">Aucun client dans cette liste.</p>}
            <div className="sv-list">
              {shown.map((c: any) => (
                <button key={c.key} className="sv-client" onClick={() => open(c.key)}>
                  <div className="sv-row"><b>{c.client}</b><span className={`sv-chip ${STATE_TONE[c.etat]}`}>{c.etat}</span></div>
                  {c.accepte > 0 ? (
                    <>
                      <Bar value={c.pct_recu} />
                      <div className="sv-row sv-small"><span>Reçu {money(c.recu)} · {pct(c.pct_recu)}</span><span>Reste {money(c.reste)} · {pct(c.pct_reste)}</span></div>
                      <div className="sv-small sv-muted">Devis accepté {money(c.accepte)} {c.devise}</div>
                    </>
                  ) : c.nb_attente > 0 ? (
                    <div className="sv-small sv-muted">{c.nb_attente} devis en attente · {money(c.en_attente)} {c.devise}</div>
                  ) : (
                    <div className="sv-small sv-muted">Devis refusé</div>
                  )}
                </button>
              ))}
            </div>
            {ov.retires.length > 0 && (
              <details className="sv-trash">
                <summary>Devis retirés · {ov.retires.length}</summary>
                {ov.retires.map((r: any) => (
                  <div className="sv-pay" key={r.id}>
                    <div><b>{r.client}</b><div className="sv-small sv-muted">{r.numero} · {money(r.montant)} {r.devise}</div></div>
                    <button className="btn btn-line btn-small" onClick={() => restore(r.id)}>Restaurer</button>
                  </div>
                ))}
              </details>
            )}
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

function ContactCard({ d, onSaved }: { d: any; onSaved: () => void }) {
  const [phone, setPhone] = useState(d.telephone || "");
  const [note, setNote] = useState(d.note || "");
  const [saved, setSaved] = useState("");
  const save = async () => {
    if (phone === (d.telephone || "") && note === (d.note || "")) return;
    try { await api.trackingInfo(d.key, { phone, note }); setSaved("Enregistré"); onSaved(); } catch (e: any) { setSaved(e?.message || "Erreur"); }
  };
  const wa = waLink(phone);
  return (
    <section className="card-box sv-contact">
      <label>Téléphone<input type="tel" inputMode="tel" value={phone} placeholder="ex. 77 123 45 67" onChange={(e) => { setPhone(e.target.value); setSaved(""); }} onBlur={save} /></label>
      {phone.replace(/\D/g, "").length >= 6 && (
        <div className="sv-actions">
          <a className="btn btn-line btn-small" href={`tel:${phone.replace(/[^\d+]/g, "")}`}>Appeler</a>
          {wa && <a className="btn btn-line btn-small" href={wa} target="_blank" rel="noreferrer">WhatsApp</a>}
        </div>
      )}
      <label>Note<textarea rows={2} value={note} placeholder="Ex. paie par Wave, rappeler après le 15…" onChange={(e) => { setNote(e.target.value); setSaved(""); }} onBlur={save} /></label>
      {saved && <p className="sv-muted">{saved}</p>}
    </section>
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
            {d.message_point && <button className="btn btn-line btn-small" onClick={() => shareText(d.message_point, `Point ${d.client}`).catch(() => {})}>Envoyer le point au client</button>}
          </section>
        )}
        {err && <p className="error">{err}</p>}
        <ContactCard key={d.key + (d.telephone || "")} d={d} onSaved={load} />
        <h2 className="sv-h2">Devis</h2>
        {d.devis.map((q: any) => (
          <section className="card-box sv-quote-card" key={q.id}>
            <div className="sv-row"><b>{q.numero}</b><span className={`sv-chip ${q.decision === "accepted" ? "ok" : q.decision === "declined" ? "off" : "wait"}`}>{DECISION_FR[q.decision]}</span></div>
            <div className="sv-small sv-muted">{[q.titre, q.lieu].filter(Boolean).join(" · ")}{q.brouillon ? " · brouillon" : ""}</div>
            <div className="sv-row"><span>Montant du devis</span><b>{money(q.montant)} {q.devise}</b></div>
            {q.decision === "pending" && !q.brouillon && q.attente_jours > 0 && <div className="sv-small sv-muted">Sans réponse depuis {q.attente_jours} j</div>}
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
            {q.decision === "accepted" && q.reste > 0 && (
              <label className="sv-collect">Prochain encaissement prévu le
                <input type="date" value={q.collecte || ""} onChange={(e) => run(() => api.trackingCollect(q.id, e.target.value || null))} />
              </label>
            )}
            {q.decision === "accepted" && (
              <div className="sv-actions">
                <button className="btn btn-copper btn-small" onClick={() => setOpen(open === q.id ? "" : q.id)}>{open === q.id ? "Fermer" : "J'ai reçu un paiement"}</button>
                {q.reste > 0 && !d.factures_solde.length && (
                  <button className="btn btn-line btn-small" onClick={() => run(async () => { const r = await api.trackingBalance(q.id); nav(`/factures/${r.id}`); })}>Facture de reliquat</button>
                )}
              </div>
            )}
            {open === q.id && <ReceiptForm quote={q} onDone={() => { setOpen(""); load(); }} />}
            <button className="sv-remove" onClick={() => window.confirm(`Retirer le devis ${q.numero} du suivi ? Tu pourras le restaurer.`) && run(() => api.trackingRemove(q.id))}>Retirer ce devis</button>
          </section>
        ))}
        {d.retires.length > 0 && (
          <details className="sv-trash">
            <summary>Devis retirés · {d.retires.length}</summary>
            {d.retires.map((r: any) => (
              <div className="sv-pay" key={r.id}><div><b>{r.numero}</b> <span className="sv-muted">· {money(r.montant)} FCFA</span></div>
                <button className="btn btn-line btn-small" onClick={() => run(() => api.trackingRestore(r.id))}>Restaurer</button></div>
            ))}
          </details>
        )}
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
        <SuiviChat k={d.key} title={`💬 Parler à UniC de ${d.client}`} onChanged={load}
          hint="Ex. « il a accepté », « j'ai reçu 200 000 en Wave », « rappelle-moi de le relancer le 15 »" />
      </div>
    </div>
  );
}
