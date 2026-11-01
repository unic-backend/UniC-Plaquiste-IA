import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, apiUrl, downloadAuth, Interrupted, isNative, net, Stopped, type ChatMessage } from "./api";
import { MessageRow } from "./App";
import { groupByDate, Typing } from "./Chrome";
import * as I from "./Icons";
import { md } from "./markdown";

/** UniC Code : le maître. Une zone de saisie ; chaque travail est une conversation à part (menu ☰ de cette page, rien que les travaux de UniC Code).
 *  Il a le cerveau du chat (courrier, agenda, devis, factures, fichiers…) et deux développeurs en fond : modifier UniC AI (tout le dépôt) et
 *  créer un projet (ZIP + aperçu). Il montre ses étapes, rend le résultat mis en forme, et ne supprime jamais un mail sans le clic du patron. */

const STATUS: Record<string, string> = { working: "En cours", done: "Livré", proposed: "À valider", merged: "Fusionné", failed: "Échec", closed: "Arrêté" };
const FINISHED = ["done", "merged", "failed", "closed"];
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const MIN = 3;
const STEP = (s: string) => s.replace(/…$/, "");

/** Ce que l'IA a fait, dans l'ordre : en direct pendant le travail, repliable ensuite. */
function Steps({ steps, live }: { steps?: string[]; live?: boolean }) {
  if (!steps?.length) return null;
  return (
    <details className="uc-steps" open={live}>
      <summary>{live ? "Je travaille…" : `${steps.length} étape${steps.length > 1 ? "s" : ""}`}</summary>
      <ol>{steps.map((s, i) => <li key={i} className={live && i === steps.length - 1 ? "now" : ""}>{STEP(s)}</li>)}</ol>
    </details>
  );
}

/** Nettoyage du courrier proposé par l'IA : rien n'est supprimé avant ce clic (corbeille de Gmail, récupérable 30 jours). */
function CleanupCard({ c }: { c: { ids: string[]; count: number; by?: Record<string, number>; examples?: { from: string; subject: string }[] } }) {
  const [left, setLeft] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => {   // ce qui est déjà parti à la corbeille ne se propose plus
    net.mailCleanup().then((r) => { const now = new Set(r.candidates.map((x) => x.id)); setLeft(c.ids.filter((id) => now.has(id))); }).catch(() => setLeft(c.ids));
  }, [c.ids]);
  const trash = async () => {
    if (!left?.length || busy) return;
    if (!window.confirm(`Mettre ${left.length} mail${left.length > 1 ? "s" : ""} à la corbeille ? Récupérables 30 jours dans Gmail.`)) return;
    setBusy(true); setMsg("");
    try { const r = await net.mailTrash(left); setMsg(`✓ ${r.trashed} mail${r.trashed > 1 ? "s" : ""} à la corbeille (récupérables 30 jours).`); setLeft([]); }
    catch (e: any) { setMsg(e?.message || "Impossible pour l'instant."); }
    finally { setBusy(false); }
  };
  return (
    <div className="uc-card">
      <b>{left === null ? "Courrier…" : left.length ? `${left.length} mail${left.length > 1 ? "s" : ""} inutile${left.length > 1 ? "s" : ""}` : "Courrier nettoyé"}</b>
      {c.by && <p className="hint">{Object.entries(c.by).map(([k, n]) => `${n} ${k}`).join(" · ")}</p>}
      {!!c.examples?.length && <ul className="uc-ex">{c.examples.map((e, i) => <li key={i}><span>{e.from}</span> {e.subject}</li>)}</ul>}
      {!!left?.length && <button className="btn btn-copper btn-small" disabled={busy} onClick={trash}>Mettre à la corbeille</button>}
      {msg && <p className="hint" role="status">{msg}</p>}
    </div>
  );
}

/** Un travail confié à un développeur (projet à part, ou modification d'UniC AI) : état, résultat, actions. */
function JobCard({ item, onChange }: { item: any; onChange: () => void }) {
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [c, setC] = useState<any>(null);
  const app = item.type === "app";
  useEffect(() => {   // état des tests d'une proposition prête
    if (!(app && item.status === "proposed")) return;
    let off = false;
    const read = () => api.repairJob(item.id).then((x) => !off && setC(x?.checks)).catch(() => {});
    read();
    const t = setInterval(() => { if (!["success", "failure"].includes(c?.state)) read(); }, 8000);
    return () => { off = true; clearInterval(t); };
  }, [app, item.id, item.status, c?.state]);
  const act = async (key: string, fn: () => Promise<any>, ok?: (r: any) => string) => {
    setBusy(key); setMsg("");
    try { const r = await fn(); if (ok) setMsg(ok(r)); onChange(); }
    catch (e: any) { setMsg(e?.message || "Erreur"); }
    finally { setBusy(""); }
  };
  const preview = async () => {
    setBusy("ap"); setMsg("");
    try { const r = await api.codePreviewLink(item.id); window.open(apiUrl(r.path), "_blank", "noopener"); }
    catch (e: any) { setMsg(e?.message || "Aperçu indisponible"); }
    finally { setBusy(""); }
  };
  const files: string[] = item.files || [];
  return (
    <div className="uc-card">
      <div className="uc-meta">
        <span className={`at-tag s-${item.status}`}>{STATUS[item.status] || item.status}</span>
        <b>{app ? "Modification d'UniC AI" : item.title || "Projet"}</b>
      </div>
      {item.status === "working" && (
        <p className="uc-wait"><span>Mon développeur travaille<span className="uc-dots" aria-hidden="true" /></span>
          <span className="hint">5 à 40 minutes. Tu peux quitter l'écran : le travail continue.</span></p>
      )}
      {item.summary && item.status !== "working" && <div className="md uc-summary" dangerouslySetInnerHTML={{ __html: md(item.summary) }} />}
      {item.error && <p className="error uc-summary">{item.error}</p>}
      {files.length > 0 && <details className="uc-files"><summary>{files.length} fichier{files.length > 1 ? "s" : ""}</summary><ul>{files.map((f) => <li key={f}>{f}</li>)}</ul></details>}
      {app && item.status === "proposed" && (
        <p className={c?.state === "success" ? "hint ic" : c?.state === "failure" ? "error" : "hint"}>
          {c ? (c.state === "success" ? "✓ " : "") + (c.detail || c.state) : "Lecture des tests…"}
        </p>
      )}
      <div className="row-actions">
        {!app && item.status === "done" && item.preview && <button className="btn btn-copper btn-small" disabled={!!busy} onClick={preview}><I.Eye size={16} /> Aperçu</button>}
        {!app && item.status === "done" && item.zip && (
          <button className="btn btn-line btn-small" disabled={!!busy}
            onClick={() => act("zip", () => downloadAuth(`/api/code/projects/${item.id}/zip`, `UniC-Code-${(item.title || "projet").replace(/[^\w]+/g, "-").slice(0, 40)}.zip`))}>Télécharger (ZIP)</button>
        )}
        {app && item.status === "proposed" && (
          <>
            <button className="btn btn-copper btn-small" disabled={c?.state !== "success" || !!busy}
              onClick={() => window.confirm("Fusionner cette modification dans l'appli ?") && act("merge", () => api.mergeJob(item.id), (r) => r.note)}>Fusionner</button>
            {item.pr_url && <a className="btn btn-line btn-small" href={item.pr_url} target="_blank" rel="noreferrer">Voir le code</a>}
            <button className="btn btn-ghost btn-small" disabled={!!busy} onClick={() => act("refuse", () => api.closeJob(item.id))}>Refuser</button>
          </>
        )}
        {item.status === "working" && (
          <button className="btn btn-ghost btn-small" disabled={!!busy}
            onClick={() => window.confirm("Arrêter ce travail ? Ce qui est déjà dépensé n'est pas rendu.") && act("stop", () => (app ? api.closeJob(item.id) : api.codeClose(item.id)))}>Arrêter</button>
        )}
      </div>
      {msg && <p className="hint" role="status">{msg}</p>}
    </div>
  );
}

type Row = { key: string; kind: "conv" | "item"; id: string; title: string; sub: string; status: string; updated_at?: string };

export function UniCCode() {
  const [d, setD] = useState<any>(null);
  const [sel, setSel] = useState<{ kind: "conv" | "item"; id: string } | null>(null);
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [drawer, setDrawer] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<{ status: string; steps: string[]; text: string }>({ status: "", steps: [], text: "" });
  const [msg, setMsg] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const ctl = useRef<AbortController | null>(null);
  const inflight = useRef<string | undefined>(undefined);
  const turn = useRef(0);

  const load = useCallback(() => api.code().then(setD).catch((e) => setMsg(e?.message || "Erreur")), []);
  useEffect(() => { load(); }, [load]);
  const items: any[] = d?.items || [];
  const cid = sel?.kind === "conv" ? sel.id : "";
  const legacy = sel?.kind === "item" ? items.find((i) => i.id === sel.id) : null;
  const connected = !!d?.github?.connected;

  useEffect(() => {   // des développeurs travaillent en fond : l'écran se rafraîchit seul
    if (!items.some((i) => i.status === "working")) return;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [d, load]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length, live.steps.length, live.text, sel?.id]);
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

  /** Le serveur termine seul un travail commencé (appli quittée, réseau coupé) : on attend sa réponse. */
  const follow = useCallback(async (id: string) => {
    const my = ++turn.current;
    setBusy(true);
    setLive({ status: "Je termine le travail…", steps: [], text: "" });
    const until = Date.now() + 25 * 60_000;
    while (turn.current === my && Date.now() < until) {
      try {
        const c = await api.getConversation(id);
        if (turn.current !== my) return;
        setMsgs(c.messages || []);
        if (!c.working) break;
      } catch { /* réseau absent : on réessaie */ }
      await new Promise((r) => setTimeout(r, 3000));
    }
    if (turn.current === my) { setBusy(false); setLive({ status: "", steps: [], text: "" }); load(); }
  }, [load]);

  const open = useCallback(async (kind: "conv" | "item", id: string) => {
    turn.current++;
    setDrawer(false); setMsg(""); setBusy(false); setLive({ status: "", steps: [], text: "" });
    setSel({ kind, id });
    setMsgs([]);
    if (kind === "conv") {
      try {
        const c = await api.getConversation(id);
        setMsgs(c.messages || []);
        if (c.working) follow(id);
      } catch (e: any) { setMsg(e?.message || "Travail introuvable"); }
    }
  }, [follow]);
  const fresh = () => { turn.current++; setSel(null); setMsgs([]); setBusy(false); setLive({ status: "", steps: [], text: "" }); setDrawer(false); setMsg(""); setTimeout(() => area.current?.focus(), 50); };

  async function send() {
    const message = text.trim();
    if (message.length < MIN || busy) return;
    const my = ++turn.current;
    setText(""); setMsg(""); setBusy(true);
    setLive({ status: "Je réfléchis…", steps: [], text: "" });
    setMsgs((m) => [...m, { id: `u${Date.now()}`, role: "user", content: message }]);
    const abort = new AbortController();
    ctl.current = abort;
    let convId = cid || undefined;
    try {
      const out = await api.chatStream({ message, conversation_id: convId, deep: false, code: true }, (ev) => {
        if (ev.t === "conv" && ev.conversation_id) { inflight.current = convId = ev.conversation_id; setSel({ kind: "conv", id: ev.conversation_id }); }
        else if (ev.t === "status") setLive((l) => ({ ...l, status: ev.text || "", steps: ev.text && ev.text !== "Je réfléchis…" && !l.steps.includes(ev.text) ? [...l.steps, ev.text] : l.steps }));
        else if (ev.t === "delta") setLive((l) => ({ ...l, text: l.text + (ev.text || "") }));
        else if (ev.t === "reset") setLive((l) => ({ ...l, text: "" }));
      }, abort.signal);
      if (turn.current !== my) return;
      setSel({ kind: "conv", id: out.conversation_id });
      setMsgs((m) => [...m, out.message]);
      load();
    } catch (e: any) {
      if (turn.current !== my) return;
      if (e instanceof Stopped) setMsgs((m) => [...m, { id: `stop${Date.now()}`, role: "assistant", content: "⏹ Arrêté à ta demande." }]);
      else if (e instanceof Interrupted) { const id = e.conversationId || convId; if (id) { setSel({ kind: "conv", id }); follow(id); return; } setMsgs((m) => [...m, { id: "err", role: "assistant", content: "Connexion coupée. Rouvre le travail dans le menu ☰." }]); }
      else setMsgs((m) => [...m, { id: "err", role: "assistant", content: e?.message || "Erreur" }]);
    } finally {
      if (turn.current === my) { setBusy(false); setLive({ status: "", steps: [], text: "" }); inflight.current = undefined; }
    }
  }
  function stop() {
    ctl.current?.abort();
    const id = inflight.current || cid;
    if (id) api.stopTurn(id).catch(() => {});
  }
  const remove = async () => {
    if (!sel || !window.confirm("Supprimer ce travail de la liste ?")) return;
    try {
      if (sel.kind === "conv") await api.deleteConversation(sel.id);
      else if (legacy?.type === "app") await api.deleteJob(sel.id);
      else await api.codeDelete(sel.id);
      fresh(); load();
    } catch (e: any) { setMsg(e?.message || "Impossible de supprimer."); }
  };

  const rows: Row[] = [
    ...(d?.convs || []).map((c: any): Row => ({ key: "c" + c.id, kind: "conv", id: c.id, title: c.title, status: c.working ? "working" : "done", sub: c.working ? "En cours" : "Travail", updated_at: c.updated_at })),
    ...items.filter((i) => !i.conv_id).map((i): Row => ({ key: "i" + i.id, kind: "item", id: i.id, title: i.title, status: i.status, sub: `${i.type === "app" ? "Mon IA" : "Projet"} · ${STATUS[i.status] || i.status}`, updated_at: i.created_at })),
  ].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  const groups = groupByDate(rows);
  const working = rows.some((r) => r.status === "working");
  const itemById = (id: string) => items.find((i) => i.id === id);
  const canRemove = !!sel && !busy && (sel.kind === "conv" || (legacy && FINISHED.includes(legacy.status)));

  return (
    <div className="uc">
      <div className="uc-bar">
        <button className="btn btn-line btn-small" aria-label="Travaux de UniC Code" aria-expanded={drawer} onClick={() => setDrawer(true)}>
          <I.Menu size={18} /> Travaux{working && <i className="uc-dot s-working" aria-label="travail en cours" />}
        </button>
        <span className="uc-bar-actions">
          {canRemove && <button className="btn btn-ghost btn-small" onClick={remove}><I.Trash size={16} /></button>}
          <button className="btn btn-ghost btn-small" onClick={fresh}><I.Plus size={16} /> Nouveau</button>
        </span>
      </div>

      {/* menu et voile rendus à la racine : la barre « Retour » et l'animation d'entrée de l'écran ne peuvent pas passer par-dessus */}
      {createPortal(<>
        <div className={`uc-scrim ${drawer ? "show" : ""}`} onClick={() => setDrawer(false)} />
        <aside className={`uc-drawer ${drawer ? "open" : ""}`} aria-label="Travaux de UniC Code" aria-hidden={!drawer}>
          <div className="uc-drawer-head"><b>UniC Code</b>
            <button className="uc-x" aria-label="Fermer" onClick={() => setDrawer(false)}><I.Close size={20} /></button></div>
          <button className="btn new-chat" onClick={fresh}>+ Nouveau travail</button>
          <div className="uc-list">
            {rows.length === 0 && <div className="conv-empty">Aucun travail pour l'instant.</div>}
            {groups.map((g) => (
              <div key={g.label}>
                <div className="conv-label">{g.label}</div>
                {g.rows.map((r: Row) => (
                  <button key={r.key} className={`uc-item ${sel?.id === r.id ? "active" : ""}`} onClick={() => open(r.kind, r.id)}>
                    <span className="uc-item-title">{r.title}</span>
                    <span className="uc-item-sub"><i className={`uc-dot s-${r.status}`} />{r.sub}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </aside>
      </>, document.body)}

      <div className="uc-scroll">
        <div className="uc-inner">
          {!d && <p className="hint">{msg || "Chargement…"}</p>}
          {d && !sel && !busy && msgs.length === 0 && <div className="uc-empty"><I.Code size={30} /><h2>Que dois-je faire ?</h2></div>}
          {legacy && (
            <>
              <div className="uc-ask">{legacy.request}</div>
              <JobCard item={legacy} onChange={load} />
            </>
          )}
          {msgs.map((m, i) => (
            <div key={m.id + i} className="uc-turn">
              {m.role === "assistant" && <Steps steps={m.meta?.steps} />}
              <MessageRow m={m} />
              {m.role === "assistant" && m.meta?.structured?.cleanup && <CleanupCard c={m.meta.structured.cleanup} />}
              {m.role === "assistant" && (m.meta?.structured?.jobs || []).map((j: any) => {
                const it = itemById(j.id);
                return it ? <JobCard key={j.id} item={it} onChange={load} /> : null;
              })}
            </div>
          ))}
          {busy && (
            <div className="uc-turn">
              <Steps steps={live.steps} live />
              <Typing deep={false} web status={live.status} liveHtml={live.text ? md(live.text) : undefined} />
            </div>
          )}
          <div ref={end} />
        </div>
      </div>

      <div className="composer-wrap">
        {msg && d && <p className="hint uc-msg" role="status">{msg}</p>}
        {d && !connected && <p className="error uc-msg">Connecte GitHub dans Atelier › GitHub : mes développeurs l'utilisent. Le reste du travail (courrier, devis…) marche déjà.</p>}
        <div className="composer">
          <textarea
            ref={area}
            rows={1}
            aria-label="Décris le travail"
            placeholder="Décris le travail à faire…"
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
            <button className={`send round ${busy ? "stop" : ""}`} aria-label={busy ? "Arrêter" : "Envoyer"} disabled={!busy && text.trim().length < MIN}
              onClick={() => (busy ? stop() : send())}>
              {busy ? <I.Stop /> : <I.ArrowUp />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
