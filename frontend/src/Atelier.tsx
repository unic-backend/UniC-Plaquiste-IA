import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import * as I from "./Icons";

/** Atelier : UniC se surveille, se corrige (propositions testées, fusion au clic) et crée ses agents. */

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "jamais");
const KIND: Record<string, string> = { error: "Erreur", sleeping: "Agent endormi", check: "Contrôle", tool: "Agent" };
const JOB: Record<string, string> = { working: "UniC code…", proposed: "Prête", merged: "Fusionnée", failed: "Échec", closed: "Refusée" };

// Même règle que le serveur (repair.is_release_request) : « donne le nouvel APK » est une publication, pas du code à écrire.
const RELEASE_RE = /\b(apk|d[ée]ploie\w*|red[ée]ploie\w*|mise? en ligne|render|nouveau lien|new lien)\b/i;
const CODE_VERB_RE = /\b(ajoute\w*|corrige\w*|modifie\w*|change\w*|supprime\w*|retire\w*|affiche\w*|cr[ée]e\w*|bouton|page)\b/i;
const isRelease = (t: string) => t.trim().length <= 160 && RELEASE_RE.test(t) && !CODE_VERB_RE.test(t);
const TONE: Record<string, string> = { ok: "hint ic", ready: "hint ic", pending: "hint", building: "hint", old: "error", failed: "error", unknown: "hint" };

/** Publication : version en ligne sur Render et APK, avec le lien dès qu'il est prêt. Se rafraîchit seul pendant une construction. */
function Release({ connected, onMsg }: { connected: boolean; onMsg: (m: string) => void }) {
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.release().then(setR).catch((e) => onMsg(e?.message || "Erreur")), [onMsg]);
  useEffect(() => { if (connected) load(); }, [connected, load]);
  const waiting = r && (r.apk?.state === "building" || r.deploy?.state === "pending");
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(load, 12000);
    return () => clearInterval(t);
  }, [waiting, load]);
  const build = async () => {
    setBusy(true); onMsg("");
    try { const x = await api.buildApk(); onMsg(x.note); await load(); } catch (e: any) { onMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  if (!connected) return null;
  return (
    <section className="card-box">
      <div className="at-head"><h3>Publication</h3>
        <button className="btn btn-line btn-small" onClick={load}><I.Refresh size={15} /> Actualiser</button></div>
      {!r && <p className="hint">Lecture de l'état…</p>}
      {r && (
        <>
          <p className={TONE[r.deploy.state]}>{r.deploy.state === "ok" ? "✓ " : ""}<b>Render</b> · {r.deploy.detail} {r.latest && <span className="hint">(version {r.latest})</span>}</p>
          <p className={TONE[r.apk.state]}>{r.apk.state === "ready" ? "✓ " : ""}<b>APK</b> · {r.apk.detail}</p>
          <div className="row-actions">
            <button className="btn btn-copper btn-small" disabled={busy || r.apk.state === "building"} onClick={build}>
              {r.apk.state === "building" ? "Construction…" : "Nouvel APK"}</button>
            {r.apk.url && r.apk.state !== "building" && <a className="btn btn-line btn-small" href={r.apk.url} target="_blank" rel="noreferrer">Ouvrir le lien de l'APK</a>}
          </div>
          {r.apk.url && <p className="hint">Sur la page : « Artifacts » en bas, télécharge l'APK, décompresse, installe.</p>}
        </>
      )}
    </section>
  );
}

export function Atelier() {
  const [d, setD] = useState<any>(null);
  const [check, setCheck] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [ask, setAsk] = useState("");
  const [gh, setGh] = useState({ token: "", repo: "", base: "", deploy_hook: "" });
  const [ag, setAg] = useState({ name: "", mission: "", every_hours: "24" });
  const [jobs, setJobs] = useState<Record<string, any>>({});
  const [open, setOpen] = useState<Record<string, any>>({});

  const load = () => api.selfcare().then(setD).catch((e) => setMsg(e?.message || "Erreur"));
  useEffect(() => { load(); }, []);
  useEffect(() => {   // une correction est en cours : on rafraîchit seul
    if (!d?.jobs?.some((j: any) => j.status === "working") && !d?.agents?.some((a: any) => a.running)) return;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [d]);
  useEffect(() => {   // état des tests des propositions prêtes
    (d?.jobs || []).filter((j: any) => j.status === "proposed").forEach((j: any) =>
      api.repairJob(j.id).then((x) => setJobs((m) => ({ ...m, [j.id]: x }))).catch(() => {}));
  }, [d]);

  const act = async (key: string, fn: () => Promise<any>, ok?: (r: any) => string) => {
    setBusy(key); setMsg("");
    try { const r = await fn(); if (ok) setMsg(ok(r)); await load(); }
    catch (e: any) { setMsg(e?.message || "Erreur"); }
    finally { setBusy(""); }
  };

  if (!d) return <div className="page"><div className="page-inner"><h1>Atelier</h1><p className="hint">{msg || "Chargement…"}</p></div></div>;
  const connected = d.github?.connected;
  return (
    <div className="page">
      <div className="page-inner atelier">
        <h1>Atelier</h1>
        <p className="lede">UniC se surveille, se répare et crée ses agents. Rien ne change en ligne sans ton clic « Fusionner ».</p>
        {msg && <p className="hint" role="status">{msg}</p>}
        <Release connected={!!connected} onMsg={setMsg} />

        <section className="card-box">
          <div className="at-head"><h3>Travail automatique</h3>
            <button className={`btn btn-small ${d.auto_work ? "btn-line" : "btn-copper"}`} disabled={!!busy}
              onClick={() => act("auto", () => api.setAutoWork(!d.auto_work), (r) => (r.auto_work ? "Travail automatique activé." : "Travail automatique coupé : rien ne tourne seul."))}>
              {d.auto_work ? "Désactiver" : "Activer"}
            </button>
          </div>
          <p className={d.auto_work ? "hint ic" : "hint"}>
            {d.auto_work
              ? <><I.Check size={16} /> Activé : contrôle de santé chaque jour et agents actifs selon leur horaire.</>
              : "Coupé : UniC ne lance aucun contrôle ni agent tout seul. Les boutons « Vérifier maintenant » et « Lancer » marchent toujours. Il ne se modifie jamais sans ton ordre."}
          </p>
        </section>

        <section className="card-box">
          <div className="at-head"><h3>Santé</h3>
            <button className="btn btn-line btn-small" disabled={busy === "check"} onClick={() => act("check", async () => setCheck(await api.selfCheck()))}>
              <I.Refresh size={15} /> {busy === "check" ? "Vérification…" : "Vérifier maintenant"}
            </button>
          </div>
          <p className="hint">Dernier contrôle : {when(d.last_check)}{d.auto_work ? " · automatique chaque jour" : " · automatique coupé"}</p>
          {check && (
            <ul className="at-checks">
              {check.checks.map((c: any) => (
                <li key={c.nom} className={c.ok ? "ok" : "ko"}>{c.ok ? <I.Check size={16} /> : <I.Alert size={16} />}<b>{c.nom}</b><span>{c.detail}</span></li>
              ))}
            </ul>
          )}
          {d.sleeping?.length > 0 && <p className="error">Agent(s) endormi(s) : {d.sleeping.map((s: any) => s.agent).join(", ")} — relancés automatiquement.</p>}
        </section>

        {d.slow_queries?.length > 0 && (
          <section className="card-box">
            <h3>Requêtes lentes ({d.slow_queries.length})</h3>
            <p className="hint">Requêtes de base de données de plus de 200 ms depuis le dernier démarrage.</p>
            {d.slow_queries.slice(0, 8).map((q: any, i: number) => (
              <p key={i}><b>{q.ms} ms</b> · {when(q.at)}<br /><code className="at-trace">{q.sql}</code></p>
            ))}
          </section>
        )}

        <section className="card-box">
          <h3>Problèmes vus ({d.incidents.length})</h3>
          {!d.incidents.length && <p className="hint">Aucun problème ouvert.</p>}
          {d.incidents.map((i: any) => (
            <article key={i.id} className="at-item">
              <div className="at-line"><span className="at-tag">{KIND[i.kind] || i.kind}</span><span className="hint">×{i.count} · {when(i.last_at)}</span></div>
              <p>{i.message}</p>
              {open[i.id] && <pre className="at-trace">{open[i.id].detail || "Pas de trace."}</pre>}
              <div className="row-actions">
                {i.kind === "error" || i.kind === "tool"
                  ? <button className="btn btn-copper btn-small" disabled={!connected || !!busy}
                      onClick={() => act(i.id, () => api.repair({ kind: "fix", incident_id: i.id }), () => "UniC code la correction (quelques minutes).")}>Corriger</button>
                  : <span className="hint">Réglage, pas du code : se ferme seul quand c'est réparé.</span>}
                <button className="btn btn-line btn-small" onClick={() => {
                  if (open[i.id]) setOpen((o) => ({ ...o, [i.id]: undefined }));
                  else api.incident(i.id).then((x) => setOpen((o) => ({ ...o, [i.id]: x }))).catch((e) => setMsg(e?.message || "Erreur"));
                }}>{open[i.id] ? "Masquer" : "Détail"}</button>
                <button className="btn btn-ghost btn-small" onClick={() => act(i.id, () => api.setIncident(i.id, "ignored"))}>Ignorer</button>
              </div>
            </article>
          ))}
          {!connected && d.incidents.length > 0 && <p className="hint">Connecte GitHub (plus bas) pour que UniC corrige lui-même.</p>}
        </section>

        <section className="card-box">
          <h3>Améliorer UniC</h3>
          <p className="hint">Décris une correction ou une nouvelle fonction : UniC la code, ajoute un test, puis te la propose.</p>
          <textarea rows={3} value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="Ex. : ajoute le nom du chantier en haut de chaque facture" />
          <div className="row-actions">
            {isRelease(ask) ? (
              <button className="btn btn-copper btn-small" disabled={!connected || !!busy}
                onClick={() => act("apk", () => api.buildApk(), (r) => { setAsk(""); return r.note; })}>Lancer le nouvel APK</button>
            ) : (
              <>
                <button className="btn btn-copper btn-small" disabled={!connected || ask.trim().length < 10 || !!busy}
                  onClick={() => act("feat", () => api.repair({ kind: "feature", request: ask }), () => { setAsk(""); return "UniC code la fonction (quelques minutes)."; })}>Nouvelle fonction</button>
                <button className="btn btn-line btn-small" disabled={!connected || ask.trim().length < 10 || !!busy}
                  onClick={() => act("fix", () => api.repair({ kind: "fix", request: ask }), () => { setAsk(""); return "UniC cherche et corrige (quelques minutes)."; })}>Corriger un bug</button>
              </>
            )}
          </div>
        </section>

        <section className="card-box">
          <h3>Propositions</h3>
          {!d.jobs.length && <p className="hint">Aucune pour l'instant.</p>}
          {d.jobs.map((j: any) => {
            const c = jobs[j.id]?.checks;
            return (
              <article key={j.id} className="at-item">
                <div className="at-line"><span className={`at-tag s-${j.status}`}>{JOB[j.status] || j.status}</span>
                  <span className="hint">{j.kind === "feature" ? "Fonction" : "Correction"} · {when(j.created_at)}</span></div>
                <p>{j.summary || j.request || "…"}</p>
                {j.error && <p className="error">{j.error}</p>}
                {j.files?.length > 0 && <p className="hint">Fichiers : {j.files.join(", ")}</p>}
                {j.status === "proposed" && (
                  <>
                    <p className={c?.state === "success" ? "hint ic" : c?.state === "failure" ? "error" : "hint"}>
                      {c ? (c.state === "success" ? "✓ " : "") + (c.detail || c.state) : "Lecture des tests…"}
                    </p>
                    <div className="row-actions">
                      <button className="btn btn-copper btn-small" disabled={c?.state !== "success" || !!busy}
                        onClick={() => window.confirm("Fusionner cette proposition dans l'appli ?") &&
                          act(j.id, () => api.mergeJob(j.id), (r) => r.note)}>Fusionner</button>
                      {j.pr_url && <a className="btn btn-line btn-small" href={j.pr_url} target="_blank" rel="noreferrer">Voir le code</a>}
                      <button className="btn btn-ghost btn-small" onClick={() => act(j.id, () => api.closeJob(j.id))}>Refuser</button>
                    </div>
                  </>
                )}
              </article>
            );
          })}
        </section>

        <section className="card-box">
          <h3>Agents</h3>
          <p className="hint">Une mission qui tourne seule (lecture et brouillons seulement). Ex. : « chaque matin, signale les demandes de devis reçues ».</p>
          {d.agents.map((a: any) => (
            <article key={a.id} className="at-item">
              <div className="at-line"><b>{a.name}</b>
                <span className={`at-tag s-${a.status}`}>{a.running ? "En cours" : a.status === "active" ? (d.auto_work ? "Actif" : "Actif · travail auto coupé") : a.status === "proposed" ? "Proposé par UniC" : "En pause"}</span></div>
              <p className="hint">{a.mission} · {d.auto_work && a.status === "active" ? `toutes les ${a.every_hours} h` : "ne tourne pas seul"} · dernier passage : {when(a.last_run)}</p>
              {a.last_result && <p className={a.last_ok ? "" : "error"}>{a.last_result}</p>}
              <div className="row-actions">
                {a.status !== "active"
                  ? <button className="btn btn-copper btn-small" onClick={() => act(a.id, () => api.setAgent(a.id, "active"))}>Activer</button>
                  : <button className="btn btn-line btn-small" onClick={() => act(a.id, () => api.setAgent(a.id, "paused"))}>Pause</button>}
                <button className="btn btn-line btn-small" disabled={a.running} onClick={() => act(a.id, () => api.runAgent(a.id), () => "Passage lancé.")}>Lancer</button>
                <button className="btn btn-ghost btn-small" onClick={() => window.confirm(`Supprimer l'agent « ${a.name} » ?`) && act(a.id, () => api.deleteAgent(a.id))}>Supprimer</button>
              </div>
            </article>
          ))}
          <div className="at-form">
            <input placeholder="Nom de l'agent" value={ag.name} onChange={(e) => setAg({ ...ag, name: e.target.value })} />
            <textarea rows={2} placeholder="Sa mission, en une ou deux phrases" value={ag.mission} onChange={(e) => setAg({ ...ag, mission: e.target.value })} />
            <label>Toutes les
              <select value={ag.every_hours} onChange={(e) => setAg({ ...ag, every_hours: e.target.value })}>
                {[["1", "heure"], ["6", "6 heures"], ["24", "jour"], ["168", "semaine"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <button className="btn btn-copper btn-small" disabled={ag.name.trim().length < 3 || ag.mission.trim().length < 20 || !!busy}
              onClick={() => act("agent", () => api.createAgent({ name: ag.name, mission: ag.mission, every_hours: Number(ag.every_hours) }),
                () => { setAg({ name: "", mission: "", every_hours: "24" }); return "Agent créé : premier passage dans la minute."; })}>Créer l'agent</button>
          </div>
        </section>

        <section className="card-box">
          <h3>GitHub (code de l'appli)</h3>
          {connected ? (
            <>
              <p className="hint ic"><I.Check size={16} /> Connecté · {d.github.repo} · branche {d.github.base || "par défaut"} · déploiement auto {d.github.deploy_hook ? "oui" : "non"}</p>
              <button className="btn btn-ghost btn-small" onClick={() => window.confirm("Déconnecter GitHub ?") && act("gh", () => api.githubDisconnect())}>Déconnecter</button>
            </>
          ) : (
            <ol className="at-steps">
              <li>Sur github.com : Settings › Developer settings › Fine-grained tokens › Generate.</li>
              <li>Accès : seulement le dépôt <b>UniC-Plaquiste-IA</b>. Permissions : <b>Contents</b>, <b>Pull requests</b> et <b>Checks (lecture)</b>.</li>
              <li>Colle le jeton ici. Il est chiffré sur le serveur et ne s'affiche plus jamais.</li>
            </ol>
          )}
          <div className="at-form">
            {!connected && <input type="password" autoComplete="off" placeholder="Jeton GitHub" value={gh.token} onChange={(e) => setGh({ ...gh, token: e.target.value })} />}
            <input placeholder="Branche déployée par Render (vide = par défaut)" value={gh.base} onChange={(e) => setGh({ ...gh, base: e.target.value })} />
            <input type="password" autoComplete="off" placeholder="Deploy Hook Render (optionnel : mise en ligne auto)" value={gh.deploy_hook} onChange={(e) => setGh({ ...gh, deploy_hook: e.target.value })} />
            <button className="btn btn-copper btn-small" disabled={(!connected && gh.token.length < 20) || !!busy}
              onClick={() => act("gh", () => api.githubConnect(gh), () => { setGh({ token: "", repo: "", base: "", deploy_hook: "" }); return "GitHub enregistré."; })}>
              {connected ? "Mettre à jour" : "Connecter"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
