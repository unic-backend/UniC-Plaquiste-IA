import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, apiUrl, downloadAuth, isNative } from "./api";
import { groupByDate } from "./Chrome";
import * as I from "./Icons";

/** UniC Code : comme Claude Code. Une seule zone de saisie ; le serveur choisit seul entre modifier ton IA (tout le dépôt,
 *  proposition à fusionner d'un clic) et créer un projet (site, jeu, appli, script : ZIP + aperçu). Tous les travaux sont rangés
 *  dans le menu ☰ de cette page, rien que ceux de UniC Code. L'Atelier garde l'APK, la publication et la surveillance. */

const STATUS: Record<string, string> = { working: "En cours", done: "Livré", proposed: "À valider", merged: "Fusionné", failed: "Échec", closed: "Arrêté" };
const FINISHED = ["done", "merged", "failed", "closed"];
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const kindLabel = (i: any) => (i.type === "app" ? "Mon IA" : "Projet");
const MIN = 10;

export function UniCCode() {
  const [d, setD] = useState<any>(null);
  const [sel, setSel] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [checks, setChecks] = useState<Record<string, any>>({});
  const area = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(() => api.code().then(setD).catch((e) => setMsg(e?.message || "Erreur")), []);
  useEffect(() => { load(); }, [load]);

  const items: any[] = d?.items || [];
  const current = items.find((i) => i.id === sel);
  const waiting = (i: any) => i.type === "app" && i.status === "proposed" && !["success", "failure"].includes(checks[i.id]?.state);

  useEffect(() => {   // un travail est en cours (ou des tests tournent) : l'écran se rafraîchit seul
    if (!items.some((i) => i.status === "working" || waiting(i))) return;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [d, checks, load]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {   // état des tests des propositions prêtes
    items.filter((i) => i.type === "app" && i.status === "proposed").forEach((i) =>
      api.repairJob(i.id).then((x) => setChecks((m) => ({ ...m, [i.id]: x?.checks }))).catch(() => {}));
  }, [d]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [sel, current?.status]);
  useEffect(() => {   // la zone de saisie grandit avec le texte (comme dans le chat)
    const el = area.current;
    if (el) { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 180)}px`; }
  }, [text]);
  useEffect(() => {
    if (!drawer) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [drawer]);

  const act = async (key: string, fn: () => Promise<any>, ok?: (r: any) => string) => {
    setBusy(key); setMsg("");
    try { const r = await fn(); if (ok) setMsg(ok(r)); await load(); }
    catch (e: any) { setMsg(e?.message || "Erreur"); }
    finally { setBusy(""); }
  };
  const open = (id: string) => { setSel(id); setDrawer(false); setMsg(""); };
  const fresh = () => { setSel(""); setDrawer(false); setMsg(""); setTimeout(() => area.current?.focus(), 50); };

  const continuing = current?.type === "project" && current.status === "done" ? current : null;
  const connected = !!d?.github?.connected;
  const send = async () => {
    const request = text.trim();
    if (request.length < MIN || busy || !connected) return;
    setBusy("send"); setMsg("");
    try {
      const r = await api.codeTask({ request, parent_id: continuing?.id || "" });
      setText("");
      await load();
      setSel(r.id);
    } catch (e: any) { setMsg(e?.message || "Erreur"); }
    finally { setBusy(""); }
  };
  const preview = async (p: any) => {
    setBusy("ap" + p.id); setMsg("");
    try { const r = await api.codePreviewLink(p.id); window.open(apiUrl(r.path), "_blank", "noopener"); }
    catch (e: any) { setMsg(e?.message || "Aperçu indisponible"); }
    finally { setBusy(""); }
  };

  const answer = (i: any) => {
    const c = checks[i.id];
    const files: string[] = i.files || [];
    return (
      <div className="uc-answer">
        <div className="uc-meta">
          <span className={`at-tag s-${i.status}`}>{STATUS[i.status] || i.status}</span>
          <span className="hint">{kindLabel(i)} · {when(i.created_at)}</span>
        </div>
        {i.status === "working" && (
          <p className="uc-wait"><span>Claude Code travaille<span className="uc-dots" aria-hidden="true" /></span>
            <span className="hint">5 à 40 minutes. Tu peux quitter l'écran : le travail continue.</span></p>
        )}
        {i.summary && i.status !== "working" && <p className="uc-summary">{i.summary}</p>}
        {i.error && <p className="error uc-summary">{i.error}</p>}
        {files.length > 0 && (
          <details className="uc-files"><summary>{files.length} fichier{files.length > 1 ? "s" : ""}</summary>
            <ul>{files.map((f) => <li key={f}>{f}</li>)}</ul></details>
        )}
        {i.type === "app" && i.status === "proposed" && (
          <p className={c?.state === "success" ? "hint ic" : c?.state === "failure" ? "error" : "hint"}>
            {c ? (c.state === "success" ? "✓ " : "") + (c.detail || c.state) : "Lecture des tests…"}
          </p>
        )}
        <div className="row-actions">
          {i.type === "project" && i.status === "done" && i.preview && (
            <button className="btn btn-copper btn-small" disabled={!!busy} onClick={() => preview(i)}><I.Eye size={16} /> Aperçu</button>
          )}
          {i.type === "project" && i.status === "done" && i.zip && (
            <button className="btn btn-line btn-small" disabled={!!busy}
              onClick={() => act("zip" + i.id, () => downloadAuth(`/api/code/projects/${i.id}/zip`, `UniC-Code-${(i.title || "projet").replace(/[^\w]+/g, "-").slice(0, 40)}.zip`))}>
              Télécharger (ZIP)
            </button>
          )}
          {i.type === "app" && i.status === "proposed" && (
            <>
              <button className="btn btn-copper btn-small" disabled={c?.state !== "success" || !!busy}
                onClick={() => window.confirm("Fusionner cette proposition dans l'appli ?") && act(i.id, () => api.mergeJob(i.id), (r) => r.note)}>Fusionner</button>
              {i.pr_url && <a className="btn btn-line btn-small" href={i.pr_url} target="_blank" rel="noreferrer">Voir le code</a>}
              <button className="btn btn-ghost btn-small" disabled={!!busy} onClick={() => act(i.id, () => api.closeJob(i.id))}>Refuser</button>
            </>
          )}
          {i.status === "working" && (
            <button className="btn btn-ghost btn-small" disabled={!!busy}
              onClick={() => window.confirm("Arrêter ce travail ? Ce qui est déjà dépensé n'est pas rendu.") &&
                act(i.id, () => (i.type === "app" ? api.closeJob(i.id) : api.codeClose(i.id)))}>Arrêter</button>
          )}
          {FINISHED.includes(i.status) && (
            <button className="btn btn-ghost btn-small" disabled={!!busy}
              onClick={() => window.confirm("Supprimer ce travail de la liste ?") &&
                act(i.id, async () => { await (i.type === "app" ? api.deleteJob(i.id) : api.codeDelete(i.id)); setSel(""); })}>Supprimer</button>
          )}
        </div>
      </div>
    );
  };

  const groups = groupByDate(items.map((i) => ({ ...i, updated_at: i.created_at })));
  return (
    <div className="uc">
      <div className="uc-bar">
        <button className="btn btn-line btn-small" aria-label="Travaux de UniC Code" aria-expanded={drawer} onClick={() => setDrawer(true)}>
          <I.Menu size={18} /> Travaux{items.some((i) => i.status === "working") && <i className="uc-dot s-working" aria-label="travail en cours" />}
        </button>
        <button className="btn btn-ghost btn-small" onClick={fresh}><I.Plus size={16} /> Nouveau</button>
      </div>

      {/* menu et voile rendus à la racine de la page : la barre « Retour » et l'animation d'entrée de l'écran ne peuvent pas passer par-dessus */}
      {createPortal(<>
      <div className={`uc-scrim ${drawer ? "show" : ""}`} onClick={() => setDrawer(false)} />
      <aside className={`uc-drawer ${drawer ? "open" : ""}`} aria-label="Travaux de UniC Code" aria-hidden={!drawer}>
        <div className="uc-drawer-head"><b>UniC Code</b>
          <button className="uc-x" aria-label="Fermer" onClick={() => setDrawer(false)}><I.Close size={20} /></button></div>
        <button className="btn new-chat" onClick={fresh}>+ Nouveau travail</button>
        <div className="uc-list">
          {items.length === 0 && <div className="conv-empty">Aucun travail pour l'instant.</div>}
          {groups.map((g) => (
            <div key={g.label}>
              <div className="conv-label">{g.label}</div>
              {g.rows.map((i: any) => (
                <button key={i.id} className={`uc-item ${i.id === sel ? "active" : ""}`} onClick={() => open(i.id)}>
                  <span className="uc-item-title">{i.title}</span>
                  <span className="uc-item-sub"><i className={`uc-dot s-${i.status}`} />{kindLabel(i)} · {STATUS[i.status] || i.status}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside></>, document.body)}

      <div className="uc-scroll">
        <div className="uc-inner">
          {!d && <p className="hint">{msg || "Chargement…"}</p>}
          {d && !current && <div className="uc-empty"><I.Code size={30} /><h2>Que dois-je faire ?</h2></div>}
          {current && (
            <>
              <div className="uc-ask">{current.request}</div>
              {answer(current)}
            </>
          )}
          <div ref={end} />
        </div>
      </div>

      <div className="composer-wrap">
        {msg && d && <p className="hint uc-msg" role="status">{msg}</p>}
        {d && !connected && <p className="error uc-msg">Connecte GitHub dans Atelier › GitHub : UniC Code utilise la même connexion.</p>}
        <div className="composer">
          {continuing && (
            <div className="uc-chip">Suite de « {continuing.title} »
              <button aria-label="Nouveau travail à la place" onClick={fresh}><I.Close size={14} /></button></div>
          )}
          <textarea
            ref={area}
            rows={1}
            aria-label="Décris le travail"
            placeholder={continuing ? "Que changer dans ce projet ?" : "Décris le travail à faire…"}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // téléphone / tablette : « Entrée » = retour à la ligne, l'envoi se fait avec la flèche ; ordinateur : Entrée envoie
              const touch = isNative || window.matchMedia?.("(pointer: coarse)").matches;
              if (e.key === "Enter" && !e.shiftKey && !touch) { e.preventDefault(); send(); }
            }}
          />
          <div className="composer-bar">
            <span className="grow" />
            <button className="send round" aria-label="Envoyer" disabled={!connected || text.trim().length < MIN || !!busy} onClick={send}>
              <I.ArrowUp />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
