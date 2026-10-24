import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/**
 * Bibliothèque de savoir : les sources que le patron donne à l'IA (PDF, livres, documents de métier, liens) et ce qu'elle a
 * appris en cherchant. Elle s'appuie d'abord sur elles pour répondre, et dit lesquelles elle utilise.
 */
export function Bibliotheque() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const load = useCallback(() => api.library().then((d) => setRows(d.sources)).catch((e) => setMsg(e?.message || "Erreur")), []);
  useEffect(() => { load(); }, [load]);
  const run = async (what: string, fn: () => Promise<any>, ok: (r: any) => string) => {
    setBusy(what); setMsg("");
    try { setMsg(ok(await fn())); await load(); } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(""); }
  };
  const active = (rows || []).filter((r) => r.active);
  const retired = (rows || []).filter((r) => !r.active);
  const line = (r: any) => (
    <li key={r.id} className={r.active ? "" : "off"}>
      <span><b>{r.nom.replace(/^Savoir - /, "")}</b>
        <small> · {r.appris_par_ia ? "appris par l'IA" : "ta source"}{r.pages ? ` · ${r.pages} p.` : ""} · {r.passages} passage(s) · {r.date}</small>
        {r.erreur && <small className="error"> · {r.erreur}</small>}</span>
      <button className="btn btn-line btn-small" disabled={!!busy}
        onClick={() => run(r.id, () => api.libraryActive(r.id, !r.active), () => (r.active ? "Source retirée : elle reste gardée, l'IA ne la consulte plus." : "Source remise."))}>
        {r.active ? "Retirer" : "Remettre"}</button>
    </li>
  );
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Bibliothèque</h1>
        <p className="lede">Donne tes sources à l'IA : livres, PDF, normes, cours, documents de métier, liens. Elle les consulte en premier et dit lesquelles elle utilise.
          Ce qu'elle apprend en cherchant y est rangé aussi.</p>
        <section className="card-box lib-add">
          <button className="btn btn-copper" disabled={!!busy} onClick={() => ref.current?.click()}>{busy === "file" ? "Lecture…" : "Ajouter un fichier"}</button>
          <input ref={ref} type="file" hidden aria-label="Fichier à ajouter à la bibliothèque" accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
            onChange={(e) => {
              const f = e.target.files?.[0]; e.target.value = "";
              if (f) run("file", () => api.libraryAddFile(f), (r) => `« ${r.nom} » ajouté${r.pages ? ` (${r.pages} pages lues)` : ""}.`);
            }} />
          <div className="lib-url">
            <input type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… (article, page, guide)" aria-label="Lien à apprendre" />
            <button className="btn btn-line" disabled={!!busy || !/^https?:\/\/\S{4,}/.test(url.trim())}
              onClick={() => run("url", () => api.libraryAddUrl(url.trim()), (r) => { setUrl(""); return `Page apprise : ${r.titre}.`; })}>
              {busy === "url" ? "Lecture…" : "Apprendre ce lien"}</button>
          </div>
          <p className="hint">Un gros livre peut prendre une minute à lire. Le contenu d'Internet reste à vérifier avant une décision importante.</p>
        </section>
        <Veille onMsg={setMsg} onDone={load} />
        {msg && <p className="hint" role="status">{msg}</p>}
        {!rows && <p className="hint">Chargement…</p>}
        {rows && !rows.length && <p className="hint">Bibliothèque vide : ajoute ta première source ci-dessus.</p>}
        {active.length > 0 && <><h3 className="cb-h">Sources consultées · {active.length}</h3><ul className="cb-exp-list lib-list">{active.map(line)}</ul></>}
        {retired.length > 0 && <><h3 className="cb-h">Retirées · {retired.length}</h3><ul className="cb-exp-list lib-list">{retired.map(line)}</ul></>}
      </div>
    </div>
  );
}

const ETAT: Record<string, string> = { ok: "rangé", rien: "rien de nouveau", erreur: "échec" };

/** Veille du matin : coupée par défaut ; le patron l'active ou la coupe d'un clic, choisit ses sujets et l'heure. */
function Veille({ onMsg, onDone }: { onMsg: (m: string) => void; onDone: () => void }) {
  const [v, setV] = useState<any>(null);
  const [topics, setTopics] = useState("");
  const [hour, setHour] = useState(7);
  const [busy, setBusy] = useState(false);
  const list = () => topics.split("\n").map((t) => t.trim()).filter(Boolean);
  const fill = (d: any) => { setV(d); setTopics((d.topics || []).join("\n")); setHour(d.hour ?? 7); };
  useEffect(() => { api.veille().then(fill).catch(() => setV({ on: false, topics: [], hour: 7, last: [], max_topics: 5 })); }, []);
  useEffect(() => {   // veille en cours : on suit son avancement, puis la bibliothèque se recharge
    if (!v?.running) return;
    const t = window.setInterval(() => api.veille().then((d) => { setV(d); if (!d.running) { onDone(); onMsg("Veille terminée."); } }).catch(() => {}), 5000);
    return () => window.clearInterval(t);
  }, [v?.running, onDone, onMsg]);
  const save = async (on: boolean) => {
    setBusy(true); onMsg("");
    try {
      fill(await api.setVeille(on, list(), hour));
      onMsg(on ? `Veille activée : chaque jour vers ${hour} h, rangée ici.` : "Veille coupée : plus aucune recherche automatique.");
    } catch (e: any) { onMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  const runNow = async () => {
    setBusy(true); onMsg("");
    try { await api.runVeille(); setV({ ...v, running: true }); onMsg("Veille lancée : une à deux minutes."); }
    catch (e: any) { onMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  if (!v) return null;
  const changed = list().join("\n") !== (v.topics || []).join("\n") || hour !== v.hour;
  return (
    <section className="card-box lib-veille">
      <label className="at-toggle">
        <input type="checkbox" checked={!!v.on} disabled={busy || (!v.on && !list().length)} onChange={(e) => save(e.target.checked)} />
        <span><b>Veille du matin</b> — chaque jour, l'IA lit l'actualité de tes sujets et range l'essentiel, daté et sourcé, dans la Bibliothèque.
          {v.on ? " Activée." : " Coupée."}</span>
      </label>
      <textarea rows={3} value={topics} onChange={(e) => setTopics(e.target.value)} aria-label="Sujets à surveiller, un par ligne"
        placeholder={"Un sujet par ligne (5 au plus), par exemple :\nprix du ciment et du plâtre au Sénégal\nappels d'offres BTP Dakar"} />
      <div className="lib-veille-row">
        <label>Heure <select value={hour} onChange={(e) => setHour(Number(e.target.value))} aria-label="Heure de la veille">
          {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h} h</option>)}</select></label>
        {changed && <button className="btn btn-line btn-small" disabled={busy} onClick={() => save(!!v.on && list().length > 0)}>Enregistrer</button>}
        <button className="btn btn-line btn-small" disabled={busy || v.running || !v.topics?.length || changed} onClick={runNow}>
          {v.running ? "Veille en cours…" : "Lancer maintenant"}</button>
      </div>
      {list().length > (v.max_topics || 5) && <p className="hint error">{v.max_topics || 5} sujets au plus.</p>}
      {v.last?.length > 0 && <ul className="cb-exp-list lib-list">
        {v.last.map((r: any, i: number) => <li key={i}><span><b>{r.sujet}</b><small> · {ETAT[r.etat] || r.etat}{r.apercu ? ` · ${r.apercu}` : ""}{r.detail ? ` · ${r.detail}` : ""}</small></span></li>)}
      </ul>}
      <p className="hint">{v.last_day ? `Dernière veille : ${v.last_day}. ` : ""}Une recherche courte par sujet, comptée dans les dépenses IA. Après 30 jours, une veille passe dans « Retirées ».</p>
    </section>
  );
}
