import { useEffect, useState } from "react";
import { api, apiUrl, downloadAuth } from "./api";
import * as I from "./Icons";

/** UniC Code : le moteur Claude Code. Projets (site, jeu, appli, script, document) livrés en ZIP avec aperçu ;
 *  code de l'IA elle-même proposé en pull request (fusion au clic, tests verts). L'Atelier garde l'APK, la publication et la surveillance. */

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const PROJECT: Record<string, string> = { working: "Claude code…", done: "Livré", failed: "Échec", closed: "Arrêté" };
const APP: Record<string, string> = { working: "Claude code…", proposed: "Prête", merged: "Fusionnée", failed: "Échec", closed: "Refusée" };
const TAG: Record<string, string> = { done: "proposed", working: "working", failed: "failed", closed: "closed" };
const IDEAS = [
  "Un site vitrine pour UniC Plaquiste : accueil, services, réalisations, contact WhatsApp",
  "Un jeu de memory sur les outils du plaquiste, pour mobile",
  "Une calculatrice de plaques BA13 en page web, hors ligne",
  "Un script Python qui renomme mes photos de chantier par date",
];
const short = (s: string, n = 72) => { const t = (s || "").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t; };

export function UniCCode() {
  const [d, setD] = useState<any>(null);
  const [tab, setTab] = useState<"projet" | "ia">("projet");
  const [ask, setAsk] = useState("");
  const [budget, setBudget] = useState("5");
  const [parent, setParent] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState("");
  const [checks, setChecks] = useState<Record<string, any>>({});

  const load = () => api.code().then(setD).catch((e) => setMsg(e?.message || "Erreur"));
  useEffect(() => { load(); }, []);
  useEffect(() => {   // un projet ou une correction en cours : rafraîchi tout seul
    const live = d?.projects?.some((p: any) => p.status === "working") || d?.app_jobs?.some((j: any) => j.status === "working");
    if (!live) return;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [d]);
  useEffect(() => {   // état des tests des propositions prêtes
    (d?.app_jobs || []).filter((j: any) => j.status === "proposed").forEach((j: any) =>
      api.repairJob(j.id).then((x) => setChecks((m) => ({ ...m, [j.id]: x?.checks }))).catch(() => {}));
  }, [d]);

  const act = async (key: string, fn: () => Promise<any>, ok?: (r: any) => string) => {
    setBusy(key); setMsg("");
    try { const r = await fn(); if (ok) setMsg(ok(r)); await load(); }
    catch (e: any) { setMsg(e?.message || "Erreur"); }
    finally { setBusy(""); }
  };
  const preview = async (p: any) => {
    setBusy("ap" + p.id); setMsg("");
    try { const r = await api.codePreviewLink(p.id); window.open(apiUrl(r.path), "_blank", "noopener"); }
    catch (e: any) { setMsg(e?.message || "Aperçu indisponible"); }
    finally { setBusy(""); }
  };
  const follow = (p: any) => { setTab("projet"); setParent(p); setAsk(""); window.scrollTo({ top: 0, behavior: "smooth" }); };

  if (!d) return <div className="page"><div className="page-inner"><h1>UniC Code</h1><p className="hint">{msg || "Chargement…"}</p></div></div>;
  const connected = !!d.github?.connected;
  const ready = connected && ask.trim().length >= 10 && !busy;
  const budgetPick = (
    <label className="code-budget">Plafond de dépense Claude
      <select value={budget} onChange={(e) => setBudget(e.target.value)}>
        {(d.budgets || ["2", "5", "10"]).map((b: string) => <option key={b} value={b}>{b} $</option>)}
      </select>
    </label>
  );

  const projectCard = (p: any) => {
    const isOpen = open === p.id;
    return (
      <article key={p.id} className={`at-banner s-${TAG[p.status] || p.status} ${isOpen ? "open" : ""}`}>
        <button className="at-banner-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? "" : p.id)}>
          <span className={`at-tag s-${TAG[p.status] || p.status}`}>{PROJECT[p.status] || p.status}</span>
          <span className="at-banner-title">{short(p.title || p.request)}</span>
          <span className="at-banner-date">{when(p.created_at)}</span>
          <span className="at-chev" aria-hidden="true">{isOpen ? "▴" : "▾"}</span>
        </button>
        {isOpen && (
          <div className="at-banner-body">
            {p.parent_id && <p className="hint">Suite d'un projet précédent</p>}
            <p className="hint">Demande : {short(p.request, 400)}</p>
            {p.summary && <p className="code-summary">{p.summary}</p>}
            {p.error && <p className="error">{p.error}</p>}
            {p.files?.length > 0 && <p className="hint">{p.files.length} fichier{p.files.length > 1 ? "s" : ""} : {short(p.files.join(", "), 240)}</p>}
            <div className="row-actions">
              {p.status === "done" && p.preview && (
                <button className="btn btn-copper btn-small" disabled={!!busy} onClick={() => preview(p)}><I.Eye size={16} /> Aperçu</button>
              )}
              {p.status === "done" && p.zip && (
                <button className="btn btn-line btn-small" disabled={!!busy}
                  onClick={() => act("zip" + p.id, () => downloadAuth(`/api/code/projects/${p.id}/zip`, `UniC-Code-${(p.title || "projet").replace(/[^\w]+/g, "-").slice(0, 40)}.zip`))}>
                  Télécharger (ZIP)
                </button>
              )}
              {p.status === "done" && <button className="btn btn-line btn-small" disabled={!!busy} onClick={() => follow(p)}>Continuer ce projet</button>}
              {p.status === "working" && (
                <button className="btn btn-ghost btn-small" disabled={!!busy}
                  onClick={() => window.confirm("Arrêter ce projet ? Ce qui est déjà dépensé n'est pas rendu.") && act(p.id, () => api.codeClose(p.id))}>Arrêter</button>
              )}
              {p.status !== "working" && (
                <button className="btn btn-ghost btn-small" disabled={!!busy}
                  onClick={() => window.confirm("Supprimer ce projet de la liste ?") && act(p.id, () => api.codeDelete(p.id))}>Supprimer</button>
              )}
            </div>
          </div>
        )}
      </article>
    );
  };

  const jobCard = (j: any) => {
    const isOpen = open === j.id;
    const c = checks[j.id];
    return (
      <article key={j.id} className={`at-banner s-${j.status} ${isOpen ? "open" : ""}`}>
        <button className="at-banner-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? "" : j.id)}>
          <span className={`at-tag s-${j.status}`}>{APP[j.status] || j.status}</span>
          <span className="at-banner-title">{short(j.request || j.summary || "Tâche")}</span>
          <span className="at-banner-date">{when(j.created_at)}</span>
          <span className="at-chev" aria-hidden="true">{isOpen ? "▴" : "▾"}</span>
        </button>
        {isOpen && (
          <div className="at-banner-body">
            <p className="hint">{j.kind === "feature" ? "Nouvelle fonction" : "Correction"}</p>
            {j.summary && <p className="code-summary">{j.summary}</p>}
            {j.error && <p className="error">{j.error}</p>}
            {j.files?.length > 0 && <p className="hint">Fichiers : {j.files.join(", ")}</p>}
            {j.status === "proposed" && (
              <>
                <p className={c?.state === "success" ? "hint ic" : c?.state === "failure" ? "error" : "hint"}>
                  {c ? (c.state === "success" ? "✓ " : "") + (c.detail || c.state) : "Lecture des tests…"}
                </p>
                <div className="row-actions">
                  <button className="btn btn-copper btn-small" disabled={c?.state !== "success" || !!busy}
                    onClick={() => window.confirm("Fusionner cette proposition dans l'appli ?") && act(j.id, () => api.mergeJob(j.id), (r) => r.note)}>Fusionner</button>
                  {j.pr_url && <a className="btn btn-line btn-small" href={j.pr_url} target="_blank" rel="noreferrer">Voir le code</a>}
                  <button className="btn btn-ghost btn-small" disabled={!!busy} onClick={() => act(j.id, () => api.closeJob(j.id))}>Refuser</button>
                </div>
              </>
            )}
            {j.status === "working" && (
              <div className="row-actions">
                <button className="btn btn-ghost btn-small" disabled={!!busy}
                  onClick={() => window.confirm("Arrêter cette tâche ?") && act(j.id, () => api.closeJob(j.id))}>Arrêter</button>
              </div>
            )}
          </div>
        )}
      </article>
    );
  };

  return (
    <div className="page">
      <div className="page-inner atelier unic-code">
        <h1><I.Code size={24} /> UniC Code</h1>
        <p className="lede">Le moteur Claude Code : il crée, teste et livre. Rien n'est publié sans toi.</p>
        {msg && <p className="hint" role="status">{msg}</p>}
        {!connected && <p className="error">Connecte GitHub dans Atelier › GitHub : UniC Code utilise la même connexion.</p>}

        <div className="seg" role="tablist" aria-label="Type de travail">
          <button role="tab" aria-selected={tab === "projet"} className={tab === "projet" ? "on" : ""} onClick={() => setTab("projet")}>Projet</button>
          <button role="tab" aria-selected={tab === "ia"} className={tab === "ia" ? "on" : ""} onClick={() => { setTab("ia"); setParent(null); }}>Mon IA</button>
        </div>

        {tab === "projet" ? (
          <section className="card-box">
            <h3>{parent ? "Continuer le projet" : "Nouveau projet"}</h3>
            {parent ? (
              <p className="hint">Suite de « {short(parent.title || parent.request, 60)} » · <button className="link-btn" onClick={() => setParent(null)}>annuler</button></p>
            ) : (
              <p className="hint">Site, jeu, application, script, outil, document… Livré en ZIP, avec un aperçu à ouvrir sur le téléphone.</p>
            )}
            <textarea rows={4} value={ask} onChange={(e) => setAsk(e.target.value)}
              placeholder={parent ? "Ex. : ajoute une page tarifs et un mode sombre" : "Décris ce que Claude doit créer…"} />
            {!parent && !ask && (
              <div className="chips">
                {IDEAS.map((x) => <button key={x} className="chip" onClick={() => setAsk(x)}>{short(x, 44)}</button>)}
              </div>
            )}
            {budgetPick}
            <div className="row-actions">
              <button className="btn btn-copper btn-small" disabled={!ready}
                onClick={() => act("go", () => api.codeStart({ request: ask, budget, parent_id: parent?.id || "" }),
                  () => { setAsk(""); setParent(null); return "Claude Code travaille (5 à 40 min). Tu peux quitter l'écran."; })}>
                {parent ? "Lancer la suite" : "Lancer"}
              </button>
            </div>
          </section>
        ) : (
          <section className="card-box">
            <h3>Améliorer mon IA</h3>
            <p className="hint">Claude Code a accès à tout le dépôt d'UniC AI : il modifie et lance les tests. Proposition à fusionner d'un clic, tests verts. Les zones protégées (sécurité, secrets, déploiement) restent à toi.</p>
            <textarea rows={4} value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="Ex. : ajoute le nom du chantier en haut de chaque facture" />
            {budgetPick}
            <div className="row-actions">
              <button className="btn btn-copper btn-small" disabled={!ready}
                onClick={() => act("feat", () => api.codeApp({ kind: "feature", request: ask, budget }), () => { setAsk(""); return "Claude Code code la fonction (5 à 30 min)."; })}>Nouvelle fonction</button>
              <button className="btn btn-line btn-small" disabled={!ready}
                onClick={() => act("fix", () => api.codeApp({ kind: "fix", request: ask, budget }), () => { setAsk(""); return "Claude Code cherche et corrige (5 à 30 min)."; })}>Corriger un bug</button>
            </div>
          </section>
        )}

        <section className="card-box">
          <h3>{tab === "projet" ? "Projets" : "Propositions pour mon IA"}</h3>
          {tab === "projet"
            ? (d.projects.length ? d.projects.map(projectCard) : <p className="hint">Aucun projet pour l'instant.</p>)
            : (d.app_jobs.length ? d.app_jobs.map(jobCard) : <p className="hint">Aucune proposition pour l'instant.</p>)}
        </section>
      </div>
    </div>
  );
}
