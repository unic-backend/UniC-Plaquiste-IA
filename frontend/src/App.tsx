import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, Navigate, Route, Routes, useLocation, useMatch, useNavigate, useParams } from "react-router-dom";
import { FicheGoogle } from "./Google";
import { Voix } from "./Voix";
import { CoverLetterBox, DiagramCard, FileCard, ShareButton } from "./Share";
import { AttachRow, type Attach } from "./Attach";
import { Agenda } from "./Agenda";
import { Suivi, SuiviClient } from "./Suivi";
import { Prospects } from "./Prospects";
import { prepareFile } from "./compress";
import { toggle as toggleSpeech, useSpeech } from "./speech";
import { Couts, Courrier, Journal, Memoire, Reseaux } from "./Reseaux";
import { DraftCards, groupByDate, PageBar, ToolChips, Typing } from "./Chrome";
import * as I from "./Icons";
import { AppsList, QuickChips } from "./Shortcuts";
import { Pointage, SignaturePanel } from "./Terrain";
import { UnicVoice } from "./UnicVoice";
import { Interpreter } from "./Interpreter";
import { Atelier } from "./Atelier";
import { ConvMenu } from "./ConvTools";
import { Higgsfield } from "./Higgsfield";
import { Chantiers } from "./Chantiers";
import { useBackHandler, useScrollMemory } from "./navMemory";
import { AUTO_KEY, getBriefingTime, listenBriefingTap, scheduleBriefing } from "./briefingPlan";
import { useTheme, type ThemeMode } from "./theme";
import { pickGreeting, type Greeting } from "./greetings";
import { queueMessage, readOutbox, takeQueued, useOnline } from "./offline";
import { api, net, AuthError, Interrupted, Stopped, authStatus, clearConnection, DEFAULT_SERVER, getSavedEmail, loginWithPassword, setAccount, signOut, downloadAuth, fetchBlobUrl, shareText, getCode, getServer, hasServerField, isNative, needsServer, saveConnection, type ChatMessage, type Conv, type Usage, type User } from "./api";

function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="10" fill="#EFEAE2" />
      <rect x="14" y="12" width="10" height="40" fill="#2C4A3E" />
      <rect x="40" y="12" width="10" height="40" fill="#2C4A3E" />
      <rect x="26" y="28" width="12" height="4" fill="#B8612E" />
    </svg>
  );
}

function md(text: string) {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*(?!\s)([^*]+?)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  const out: string[] = [];
  let list: "ul" | "ol" | null = null;
  let para: string[] = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br/>")}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const num = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const head = /^#{1,4}\s+(.*)$/.exec(line);
    if (bullet || num) {
      flushPara();
      const kind = bullet ? "ul" : "ol";
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((bullet || num)![1])}</li>`);
    } else if (head) {
      flushPara(); closeList();
      out.push(`<h3>${inline(head[1])}</h3>`);
    } else if (!line.trim()) {
      flushPara(); closeList();
    } else {
      closeList();
      para.push(inline(line));
    }
  }
  flushPara(); closeList();
  return out.join("");
}

/** Chaque mot apparaît à son tour (fondu) : mise en page stable, pas de Markdown cassé en cours de route. */
function revealHtml(html: string, totalMs = 3200): string {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const words: Text[] = [];
  const walker = document.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if ((n.textContent || "").trim()) words.push(n as Text);
  const count = words.reduce((s, t) => s + (t.textContent || "").split(/\s+/).filter(Boolean).length, 0);
  const step = Math.min(45, totalMs / Math.max(1, count));
  let k = 0;
  for (const t of words) {
    const frag = document.createDocumentFragment();
    for (const part of (t.textContent || "").split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s+$/.test(part)) { frag.append(part); continue; }
      const s = document.createElement("span");
      s.className = "w";
      s.style.animationDelay = `${Math.round(k++ * step)}ms`;
      s.textContent = part;
      frag.append(s);
    }
    t.replaceWith(frag);
  }
  return tpl.innerHTML;
}

const STATUS_FR: Record<string, string> = {
  draft: "À valider", approved: "Approuvé", sent: "Envoyé", paid: "Payé", partial: "Partiel", cancelled: "Annulé", review: "En revue",
};
/** Le mot « brouillon » n'apparaît jamais sur un devis : un document pas encore approuvé est simplement « à valider ». */
const statusFr = (s?: string) => STATUS_FR[(s || "").toLowerCase()] ?? (s || "—");

function Badge({ s }: { s?: string }) {
  const v = (s || "").toLowerCase();
  if (v === "draft") return null;   // rien à afficher : l'état normal d'un document en préparation
  return <span className={`badge ${v}`}>{statusFr(v)}</span>;
}

function fmt(n: number | null | undefined, cur = ""): string {
  if (n === null || n === undefined) return "—";
  return `${new Intl.NumberFormat("fr-FR").format(n)}${cur ? ` ${cur}` : ""}`;
}

const DOC_LABEL: Record<string, string> = { quote: "Devis", invoice: "Facture", po: "Bon de commande", dn: "Bon de livraison" };

const artifactIdOf = (d: any): string | null =>
  d?.artifact_id || (d?.download_url ? (/\/artifacts\/([^/]+)\/download/.exec(d.download_url) || [])[1] || null : null);

/** Aperçu plein écran du PDF avant de le télécharger : corriger, approuver, puis télécharger. */
function PreviewModal({ kind, d, onClose, onChanged, onDownload }: {
  kind: "quote" | "invoice" | "po" | "dn"; d: any; onClose: () => void; onChanged: () => void; onDownload: (() => void) | null;
}) {
  const [imgs, setImgs] = useState<string[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const aid = artifactIdOf(d);
  useEffect(() => {
    if (!aid) { setErr("Aucun PDF pour ce document."); return; }
    api.preview(aid).then((r) => setImgs(r.images)).catch((e: Error) => setErr(e.message));
  }, [aid, d.version, d.total]);
  const canApprove = kind === "quote" && d.status !== "approved";
  return createPortal(
    <div className="preview-back" role="dialog" aria-label={`Aperçu ${d.number}`}>
      <div className="preview-head">
        <button className="tool" aria-label="Fermer l'aperçu" onClick={onClose}><I.Close size={22} /></button>
        <b>{DOC_LABEL[kind]} {d.number}</b>
        <span />
      </div>
      <div className="preview-body">
        {!imgs && !err && <p className="hint">Chargement de l'aperçu…</p>}
        {err && <p className="error">{err}</p>}
        {imgs?.map((src, i) => <img key={i} src={src} alt={`Page ${i + 1} du ${DOC_LABEL[kind].toLowerCase()}`} />)}
      </div>
      <div className="preview-actions">
        <button className="btn btn-line" onClick={() => {
          window.dispatchEvent(new CustomEvent("unic:prefill", { detail: `Corrige le ${DOC_LABEL[kind].toLowerCase()} ${d.number} : ` }));
          onClose();
        }}><I.Pencil size={16} /> Corriger</button>
        {canApprove && (
          <button className="btn btn-line" disabled={busy} onClick={async () => {
            setBusy(true);
            try { await api.approveQuote(d.id); onChanged(); } finally { setBusy(false); }
          }}><I.Check size={16} /> Approuver</button>
        )}
        {d.status === "approved" && <span className="hint ic"><I.Check size={16} /> Approuvé</span>}
        {aid && <ShareButton url={`/api/artifacts/${aid}/download`} filename={`${d.number}.pdf`} text={kind === "quote" ? d.cover_letter || "" : ""} className="btn btn-line" />}
        {onDownload && <button className="btn btn-copper" onClick={onDownload}>Télécharger</button>}
      </div>
    </div>,
    document.body,
  );
}

/** Document affiché directement dans la conversation (lignes, total, actions). */
function DocCard({ kind, id }: { kind: "quote" | "invoice" | "po" | "dn"; id: string }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(false);
  const load = () => {
    const fn = { quote: api.getQuote, invoice: api.getInvoice, po: api.getPo, dn: api.getDn }[kind];
    fn(id).then(setD).catch((e: Error) => setErr(e.message));
  };
  useEffect(load, [kind, id]);
  if (err) return <div className="doc-card"><p className="error">{err}</p></div>;
  if (!d) return <div className="doc-card">Chargement du document…</div>;
  const cur = d.currency || "";
  const priced = kind !== "dn";
  const dl = d.download_url
    ? () => downloadAuth(d.download_url, d.filename || `${d.number}.pdf`)
    : d.artifact_id
      ? () => downloadAuth(`/api/artifacts/${d.artifact_id}/download`, `${d.number}.pdf`)
      : null;
  const shareUrl: string | null = d.download_url || (d.artifact_id ? `/api/artifacts/${d.artifact_id}/download` : null);
  const who = d.customer_name || d.client_label || d.client_name || "";
  const total = d.total === null || d.total === undefined ? "total incomplet" : fmt(d.total, cur);
  const sub = [who, d.site_location, priced ? total : ""].filter(Boolean).join(" · ");
  const open = () => (artifactIdOf(d) ? setPreview(true) : undefined);
  return (
    <div className="doc-card doc-mini">
      <button className="doc-open" onClick={open} aria-label={`Ouvrir ${DOC_LABEL[kind]} ${d.number}`} disabled={!artifactIdOf(d)}>
        <span className="doc-thumb"><I.File size={26} /></span>
        <span className="doc-meta">
          <b>{DOC_LABEL[kind]} {d.number}</b>
          <span className="doc-sub">{sub || d.title}</span>
          <span className="doc-sub">{DOC_LABEL[kind]} · PDF{d.status === "approved" ? " · approuvé" : ""}</span>
        </span>
      </button>
      {priced && kind === "quote" && Array.isArray(d.price_check) && d.price_check.length > 0 && (
        <p className="error ic"><I.Alert size={16} /> {d.price_check.length} anomalie(s) de prix : ouvre le détail.</p>
      )}
      {kind === "quote" && d.prices_complete === false && (
        <p className="hint">Prix manquants sur certaines lignes : rien n'est inventé, le total est partiel.</p>
      )}
      <div className="doc-actions">
        {dl && <button className="doc-act" onClick={dl} aria-label="Télécharger le PDF" title="Télécharger"><I.File size={18} /><span>PDF</span></button>}
        {shareUrl && <ShareButton url={shareUrl} filename={d.filename || `${d.number}.pdf`} text={kind === "quote" ? d.cover_letter || "" : ""} className="doc-act" />}
        {kind === "quote" && d.status !== "approved" && (
          <button className="doc-act" onClick={async () => { await api.approveQuote(d.id); load(); }}><I.Check size={18} /><span>Approuver</span></button>
        )}
        {kind === "invoice" && d.balance_url && <ShareButton url={d.balance_url} filename={`Reliquat_${d.number}.pdf`} text={d.balance_message || ""} label="Reliquat" className="doc-act" />}
        <Link className="doc-act" to={`/${{ quote: "devis", invoice: "factures", po: "commandes", dn: "livraisons" }[kind]}/${d.id}`}><I.Note size={18} /><span>Détail</span></Link>
        {d.status === "draft" && (
          <button className="doc-act"
            onClick={async () => {
              if (!window.confirm("Retirer ce brouillon de la bibliothèque ?")) return;
              try { await net.discardDoc(kind, d.id); setD(null); setErr("Brouillon retiré."); } catch (e: any) { setErr(e.message); }
            }}>
            <I.Trash size={18} /><span>Retirer</span>
          </button>
        )}
      </div>
      {kind === "quote" && d.status === "approved" && <CoverLetterBox quote={d} url={shareUrl} filename={d.filename || `${d.number}.pdf`} onChanged={load} />}
      {preview && <PreviewModal kind={kind} d={d} onClose={() => setPreview(false)} onChanged={load} onDownload={dl} />}
    </div>
  );
}

/** Réponse qui vient d'arriver : ses mots apparaissent un à un ; un toucher affiche tout. */
function useReveal(len: number, active: boolean) {
  const [done, setDone] = useState(!active);
  useEffect(() => {
    if (!active) { setDone(true); return; }
    setDone(false);
    const id = setTimeout(() => setDone(true), 3600);
    const chat = document.querySelector(".chat");
    if (chat) chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
    return () => clearTimeout(id);
  }, [len, active]);
  return { done, skip: () => setDone(true) };
}

/** Salutation écrite lettre par lettre, à vitesse moyenne. */
function GreetingTyper({ g }: { g: Greeting }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    const id = setInterval(() => setN((c) => (c >= g.text.length ? c : c + 1)), 85);
    return () => clearInterval(id);
  }, [g.text]);
  const done = n >= g.text.length;
  return (
    <div className="greet" aria-live="polite" aria-label={g.text}>
      <span className="greet-text">{g.text.slice(0, n)}<i className={`caret ${done ? "blink" : ""}`} /></span>
      <span className={`greet-fr ${done ? "show" : ""}`}>{g.fr} · {g.lang}</span>
    </div>
  );
}

function MessageView({ m, onRegenerate, onEdit }: { m: ChatMessage; onRegenerate?: () => void; onEdit?: (t: string) => void }) {
  const [copied, setCopied] = useState(false);
  const [speakErr, setSpeakErr] = useState("");
  const [kept, setKept] = useState(!!m.validated);
  const [keepErr, setKeepErr] = useState("");
  const speech = useSpeech(m.id);
  const tw = useReveal(m.content.length, !!m.fresh && m.role === "assistant");
  const html = m.role === "assistant" && m.fresh && !tw.done ? revealHtml(md(m.content)) : md(m.content);
  const structured = m.meta?.structured;
  const arts = m.meta?.artifacts || [];
  // fichiers joints : cartes séparées, au-dessus de la question (aperçu de la photo ou du plan)
  const sent: Attach[] = m.files || (m.meta?.files || []).map((f: any) => ({ name: f.filename, mime: f.mime, id: f.id }));
  return (
    <div className={`msg ${m.role} enter`}>
      <div className="avatar">{m.role === "user" ? "Vous" : "U"}</div>
      <div className="msg-col">
      {m.role === "user" && <AttachRow items={sent} className="sent" />}
      <div className={`bubble ${m.fresh ? "fresh" : ""} ${m.fresh && !tw.done ? "typing" : ""}`} onClick={m.fresh && !tw.done ? tw.skip : undefined}>
        <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
        {m.role === "user" && (
          <div className="msg-actions">
            <button onClick={async () => { try { await navigator.clipboard.writeText(m.content); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* presse-papiers indisponible */ } }}>
              {copied ? <><I.Check size={15} /> Copié</> : <><I.Copy size={15} /> Copier</>}
            </button>
            {onEdit && <button onClick={() => onEdit(m.content)}><I.Pencil size={15} /> Modifier</button>}
          </div>
        )}
        {m.role === "assistant" && m.id !== "err" && (
          <div className="msg-actions">
            <button onClick={async () => { try { await navigator.clipboard.writeText(m.content); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* presse-papiers indisponible */ } }}>
              {copied ? <><I.Check size={15} /> Copié</> : <><I.Copy size={15} /> Copier</>}
            </button>
            {tw.done && (
              <button className={`speak-btn ${speech !== "idle" ? "on" : ""}`} aria-pressed={speech === "playing"}
                onClick={async () => setSpeakErr(await toggleSpeech(m.id, m.content))}>
                {speech === "idle" ? <><I.Speaker size={15} /> Écouter</> : speech === "loading" ? <>… Chargement</> : <><I.Stop size={15} /> Arrêter</>}
              </button>
            )}
            {onRegenerate && tw.done && <button onClick={onRegenerate}><I.Refresh size={15} /> Régénérer</button>}
            {tw.done && (
              <button aria-pressed={kept} className={kept ? "on" : ""} title="Bonne réponse : l'IA la retient et la réutilise si Claude est indisponible"
                onClick={async () => { setKeepErr(""); try { await api.validateMessage(m.id, !kept); setKept(!kept); } catch (e: any) { setKeepErr(e?.message || "Impossible"); } }}>
                <I.Check size={15} /> {kept ? "Retenu" : "Retenir"}
              </button>
            )}
            {keepErr && <span className="error">{keepErr}</span>}
            {speakErr && <span className="error">{speakErr}</span>}
          </div>
        )}
        {structured?.steps?.length ? (
          <div className="calc-card">
            <div className="calc-row">
              <div>Étape</div>
              <div>Formule</div>
              <div>Résultat</div>
            </div>
            {structured.steps.map((s: any, i: number) => (
              <div className="calc-row" key={i}>
                <div>
                  {s.label} <Badge s={s.status} />
                </div>
                <div>
                  <code>{s.formula}</code>
                </div>
                <div>
                  <strong>
                    {s.result} {s.unit}
                  </strong>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <ToolChips caps={m.meta?.capabilities} />
        <DraftCards drafts={structured?.drafts} />
        {structured?.document ? <DocCard kind={structured.document.kind} id={structured.document.id} /> : null}
        {(structured?.documents || []).map((d: any) => <DocCard key={d.id} kind={d.kind} id={d.id} />)}
        {(structured?.images || []).map((d: any) => <DiagramCard key={d.id} id={d.id} filename={d.filename} title={d.title} caption={d.caption} />)}
        {(structured?.files || []).map((f: any) => <FileCard key={f.id} id={f.id} filename={f.filename} mime={f.mime} size={f.size} />)}
        {arts.length && !structured?.document && !structured?.documents ? (
          <div className="arts">
            {arts.map((a: any) => (
              <div className="art" key={a.id || a.artifact_id}>
                <div>
                  <b>{a.filename}</b>
                  <span>
                    {a.artifact_id} · {a.status} · PDF réel
                  </span>
                </div>
                <button className="btn btn-copper btn-small" onClick={() => downloadAuth(a.download_url, a.filename)}>
                  Télécharger
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      </div>
    </div>
  );
}

type Gate = "loading" | "connect" | "error" | "ok";

function useOwner() {
  const [user, setUser] = useState<User | null>(null);
  const [gate, setGate] = useState<Gate>(needsServer() ? "connect" : "loading");
  const [error, setError] = useState("");
  const check = () => {
    if (needsServer()) {
      setGate("connect");
      return;
    }
    setGate("loading");
    api
      .me()
      .then((u) => {
        setUser(u);
        setGate("ok");
      })
      .catch((e) => {
        if (e instanceof AuthError) setGate("connect");
        else {
          setError(e.message);
          setGate("error");
        }
      });
  };
  useEffect(check, []);
  return { user, gate, error, check };
}

function Connexion({ onDone }: { onDone: () => void }) {
  const [server, setServer] = useState(getServer() || DEFAULT_SERVER);
  const [editServer, setEditServer] = useState(false);
  const [mode, setMode] = useState<"password" | "code" | "create">("password");
  const [email, setEmail] = useState(getSavedEmail());
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const base = (hasServerField ? server : "").trim().replace(/\/+$/, "");

  // Pas encore d'e-mail / mot de passe sur ce serveur : première connexion avec le code d'accès.
  useEffect(() => {
    if (hasServerField && !/^https:\/\//i.test(base)) return;
    authStatus(base).then((st) => { if (!st.account) setMode("code"); }).catch(() => {});
  }, [base]);

  const run = async (fn: () => Promise<void>) => {
    if (hasServerField && !/^https:\/\/[^\s/]+/i.test(base)) { setMsg("Adresse du serveur invalide : elle commence par https://"); return; }
    setBusy(true); setMsg("");
    try { await fn(); } catch (e: any) { setMsg(e?.message || "Connexion impossible"); } finally { setBusy(false); }
  };
  const withPassword = () => run(async () => { await loginWithPassword(base, email, password); onDone(); });
  const withCode = () => run(async () => {
    saveConnection(base, code.trim());
    try { await api.me(); } catch (e) { throw e instanceof AuthError ? new Error("Code d'accès incorrect.") : e; }
    setMode("create"); setPassword("");
  });
  const create = () => run(async () => { await setAccount(email, password); onDone(); });

  return (
    <div className="login">
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); (mode === "password" ? withPassword : mode === "code" ? withCode : create)(); }}>
        <h1>UniC AI</h1>
        {mode === "password" && <p className="hint">Connecte-toi avec ton e-mail et ton mot de passe.</p>}
        {mode === "code" && <p className="hint">Première connexion ou mot de passe oublié : entre le code d'accès de ton serveur.</p>}
        {mode === "create" && <p className="hint">Choisis l'e-mail et le mot de passe que tu utiliseras désormais (8 caractères minimum).</p>}

        {mode !== "code" && (
          <>
            <label>E-mail</label>
            <input type="email" value={email} autoComplete="username" inputMode="email" autoCapitalize="none" autoCorrect="off"
              onChange={(e) => setEmail(e.target.value)} />
            <label>{mode === "create" ? "Nouveau mot de passe" : "Mot de passe"}</label>
            <input type="password" value={password} autoComplete={mode === "create" ? "new-password" : "current-password"}
              onChange={(e) => setPassword(e.target.value)} />
          </>
        )}
        {mode === "code" && (
          <>
            <label>Code d'accès</label>
            <input type="password" value={code} autoComplete="off" onChange={(e) => setCode(e.target.value)} />
          </>
        )}
        {msg && <p className="error">{msg}</p>}
        <button className="btn btn-copper" type="submit" disabled={busy || (mode === "code" ? !code.trim() : !email.trim() || !password)}>
          {busy ? "Connexion…" : mode === "create" ? "Enregistrer et entrer" : "Se connecter"}
        </button>

        {mode === "password" && <button type="button" className="link-btn" onClick={() => { setMode("code"); setMsg(""); }}>Mot de passe oublié ? Utiliser le code d'accès</button>}
        {mode === "code" && <button type="button" className="link-btn" onClick={() => { setMode("password"); setMsg(""); }}>J'ai déjà un e-mail et un mot de passe</button>}

        {hasServerField && (editServer ? (
          <>
            <label>Adresse du serveur</label>
            <input value={server} autoCapitalize="none" autoCorrect="off" inputMode="url" onChange={(e) => setServer(e.target.value)} />
          </>
        ) : (
          <button type="button" className="link-btn muted" onClick={() => setEditServer(true)}>Serveur : {base.replace(/^https:\/\//, "")} · changer</button>
        ))}
      </form>
    </div>
  );
}


/** Une conversation du menu : ouvrir, ⋯ → épingler, renommer, supprimer (avec confirmation). */
function ConvItem({ c, active, onClose, onChange, onRemove, onMoved }: {
  c: Conv; active: boolean; onClose: () => void; onChange: (n: Partial<Conv>) => void; onRemove: () => void; onMoved: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [mode, setMode] = useState<"view" | "rename" | "confirm">("view");
  const [name, setName] = useState(c.title);
  const [err, setErr] = useState("");
  const done = () => { setMenu(false); setMode("view"); setErr(""); };
  const save = async () => {
    const t = name.trim();
    if (!t || t === c.title) return done();
    try { const r = await api.patchConversation(c.id, { title: t }); onChange({ title: r.title }); done(); } catch (e: any) { setErr(e.message); }
  };
  if (mode === "rename")
    return (
      <div className="conv-item editing">
        <input autoFocus value={name} maxLength={80} aria-label="Nouveau nom" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") done(); }} />
        <button aria-label="Enregistrer le nom" onClick={save}><I.Check size={18} /></button>
        <button aria-label="Annuler" onClick={done}><I.Close size={18} /></button>
        {err && <span className="conv-err">{err}</span>}
      </div>
    );
  if (mode === "confirm")
    return (
      <div className="conv-item confirming">
        <span>Supprimer « {c.title.length > 22 ? c.title.slice(0, 22) + "…" : c.title} » ?</span>
        <button className="danger" onClick={async () => { try { await api.deleteConversation(c.id); onRemove(); } catch (e: any) { setErr(e.message); } }}>Confirmer</button>
        <button onClick={done}>Annuler</button>
        {err && <span className="conv-err">{err}</span>}
      </div>
    );
  return (
    <div className={`conv-item ${menu ? "menu-open" : ""}`}>
      <Link to={`/c/${c.id}`} className={active ? "active" : ""} onClick={onClose}>
        {c.pinned && <I.Pin size={13} />} {c.title}
      </Link>
      <button aria-label="Options de la conversation" aria-expanded={menu} onClick={() => setMenu((m) => !m)}><I.More size={20} /></button>
      {menu && (
        <div className="conv-menu" role="menu">
          <button role="menuitem" onClick={async () => { const r = await api.patchConversation(c.id, { pinned: !c.pinned }); onChange({ pinned: r.pinned }); done(); }}>
            <I.Pin size={16} /> {c.pinned ? "Désépingler" : "Épingler"}
          </button>
          <button role="menuitem" onClick={() => { setName(c.title); setMode("rename"); }}><I.Pencil size={16} /> Renommer</button>
          <button role="menuitem" onClick={async () => { try { await api.patchConversation(c.id, { archived: !c.archived }); done(); onMoved(); } catch (e: any) { setErr(e.message); } }}>
            <I.ArrowDown size={16} /> {c.archived ? "Sortir de l'archive" : "Archiver"}</button>
          <button role="menuitem" className="danger" onClick={() => setMode("confirm")}><I.Trash size={16} /> Supprimer</button>
        </div>
      )}
    </div>
  );
}

function Shell({ user, children }: { user: User; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [convs, setConvs] = useState<Conv[]>([]);
  const [archived, setArchived] = useState<Conv[]>([]);
  const [q, setQ] = useState("");
  const loc = useLocation();
  const nav = useNavigate();
  const [stamp, setStamp] = useState(0);   // change quand une conversation est archivée ou sortie de l'archive
  const openRef = useRef(false);
  openRef.current = open;
  useScrollMemory();
  useBackHandler(() => {   // retour du téléphone : ferme d'abord ce qui est ouvert (menu latéral, menus, feuilles)
    if (openRef.current) { setOpen(false); return true; }
    const ev = new Event("unic:back", { cancelable: true });
    window.dispatchEvent(ev);
    return ev.defaultPrevented;
  });
  useEffect(() => {
    api.conversations(q).then(setConvs).catch(() => setConvs([]));
    api.conversations(q, true).then(setArchived).catch(() => setArchived([]));
  }, [q, loc.pathname, stamp]);
  const openConv = loc.pathname.startsWith("/c/") ? [...convs, ...archived].find((c) => loc.pathname === `/c/${c.id}`) : undefined;
  useEffect(() => setOpen(false), [loc.pathname]);
  const [work, setWork] = useState(0);   // erreurs à corriger + propositions prêtes (pastille de l'Atelier)
  useEffect(() => {
    if (!open) return;
    api.selfcare().then((d) => setWork(d.incidents.filter((i: any) => i.kind === "error" || i.kind === "tool").length
      + d.jobs.filter((j: any) => j.status === "proposed").length)).catch(() => {});
  }, [open]);
  useEffect(() => {
    let off: (() => void) | undefined;
    listenBriefingTap(() => nav("/")).then((f) => { off = f; }).catch(() => {});
    return () => off?.();
  }, []);
  return (
    <div className="app">
      <div className={`overlay ${open ? "show" : ""}`} onClick={() => setOpen(false)} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">UniC AI</div>
            <div className="brand-sub">UniC Plaquiste</div>
          </div>
        </div>
        <Link to="/" className="btn new-chat" onClick={() => setOpen(false)}>
          + Nouvelle conversation
        </Link>
        <button className="side-brief" onClick={() => {
          try { sessionStorage.setItem(AUTO_KEY, "briefing"); } catch { /* ignoré */ }
          setOpen(false);
          nav("/");
          window.dispatchEvent(new Event("unic:autosend"));   // déjà sur une conversation vide : lancé tout de suite
        }}>
          <I.Sun size={18} /> Briefing du jour
        </button>
        <Link to="/unic" className="side-brief side-code" onClick={() => setOpen(false)}>
          <I.Mic size={18} /> UniC vocal
        </Link>
        <Link to="/interprete" className="side-brief side-code" onClick={() => setOpen(false)}>
          <I.Globe size={18} /> Interprète
        </Link>
        <Link to="/suivi" className={`side-brief side-code ${loc.pathname.startsWith("/suivi") ? "active" : ""}`} onClick={() => setOpen(false)}>
          <I.Receipt size={18} /> Suivi des encaissements
        </Link>
        <Link to="/atelier" className={`side-brief side-code ${loc.pathname === "/atelier" ? "active" : ""}`} onClick={() => setOpen(false)}>
          <I.Code size={18} /> Atelier · Code
          {work > 0 && <span className="side-badge" aria-label={`${work} élément(s) à voir`}>{work}</span>}
        </Link>
        <input
          placeholder="Rechercher…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ background: "#24302c", color: "#efeae2", borderColor: "#3d4a45" }}
        />
        <div className="conv-list">
          {convs.length === 0 && <div className="conv-empty">{q ? "Aucun résultat." : "Aucune conversation pour l'instant."}</div>}
          {[
            ...(convs.some((c) => c.pinned) ? [{ label: "Épinglées", rows: convs.filter((c) => c.pinned) }] : []),
            ...groupByDate(convs.filter((c) => !c.pinned)),
          ].map((g) => (
            <div key={g.label}>
              <div className="conv-label">{g.label === "Épinglées" && <I.Pin size={12} />} {g.label}</div>
              {g.rows.map((c) => (
                <ConvItem key={c.id} c={c} active={loc.pathname === `/c/${c.id}`} onClose={() => setOpen(false)}
                  onChange={(next) => setConvs((x) => x.map((i) => (i.id === c.id ? { ...i, ...next } : i)))}
                  onMoved={() => { setStamp((n) => n + 1); if (loc.pathname === `/c/${c.id}`) nav("/"); }}
                  onRemove={() => { setConvs((x) => x.filter((i) => i.id !== c.id)); if (loc.pathname === `/c/${c.id}`) nav("/"); }} />
              ))}
            </div>
          ))}
          {archived.length > 0 && (
            <details className="conv-archive">
              <summary>Archivées · {archived.length}</summary>
              {archived.map((c) => (
                <ConvItem key={c.id} c={c} active={loc.pathname === `/c/${c.id}`} onClose={() => setOpen(false)}
                  onChange={(next) => setArchived((x) => x.map((i) => (i.id === c.id ? { ...i, ...next } : i)))}
                  onMoved={() => setStamp((n) => n + 1)}
                  onRemove={() => { setArchived((x) => x.filter((i) => i.id !== c.id)); if (loc.pathname === `/c/${c.id}`) nav("/"); }} />
              ))}
            </details>
          )}
        </div>
        <div className="side-foot">
          <Link to="/parametres" className={`foot-link ${loc.pathname.startsWith("/parametres") ? "active" : ""}`}>
            <I.Settings size={18} /> Paramètres
          </Link>
        </div>
      </aside>
      <section className="main">
        <div className="topbar">
          <button className="icon-btn" onClick={() => setOpen(true)} aria-label="Menu">
            <I.Menu />
          </button>
          <Logo size={22} />
          <b>UniC AI</b>
          {openConv && (
            <ConvMenu key={openConv.id} conv={openConv}
              onChange={(n) => setConvs((x) => x.map((i) => (i.id === openConv.id ? { ...i, ...n } : i)))}
              onGone={() => { setStamp((n) => n + 1); nav("/"); }} />
          )}
        </div>
        {loc.pathname === "/" || loc.pathname.startsWith("/c/") ? null : <PageBar />}
        <div className="route-anim" key={loc.pathname.startsWith("/c/") ? "/" : loc.pathname}>
          {children}
        </div>
      </section>
    </div>
  );
}

function Chat({ initialId }: { initialId?: string }) {
  const nav = useNavigate();
  const [cid, setCid] = useState<string | undefined>(initialId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<{ status: string; text: string }>({ status: "", text: "" });
  const [pending, setPending] = useState<File[]>([]);
  const [deep, setDeep] = useState(false);
  const [rec, setRec] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [apps, setApps] = useState(false);
  useEffect(() => { if (!sheet) setApps(false); }, [sheet]);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(t);
  }, [notice]);
  useEffect(() => {
    if (!isNative) return;
    let off: (() => void) | undefined;
    (async () => {
      const { Keyboard } = await import("@capacitor/keyboard");
      const root = document.documentElement;
      const show = await Keyboard.addListener("keyboardWillShow", (i) => {
        root.style.setProperty("--kb", `${i.keyboardHeight}px`);
        setTimeout(() => end.current?.scrollIntoView({ block: "end" }), 60);
      });
      const hide = await Keyboard.addListener("keyboardWillHide", () => root.style.setProperty("--kb", "0px"));
      off = () => { show.remove(); hide.remove(); root.style.setProperty("--kb", "0px"); };
    })().catch(() => {});
    return () => off?.();
  }, []);
  const sendRef = useRef<(m?: string) => void>();
  const ctl = useRef<AbortController | null>(null);   // coupe la requête en cours (bouton « Arrêter »)
  const end = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const [showDown, setShowDown] = useState(false);   // flèche « tout en bas » : visible quand on est remonté dans la conversation
  useEffect(() => {   // le champ grandit avec le texte (les retours à la ligne restent visibles)
    const t = taRef.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 180)}px`;
  }, [text]);
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);

  const justCreated = useRef<string | undefined>(undefined);
  const turn = useRef(0);                                  // chaque envoi / reprise a son numéro : seul le dernier écrit à l'écran
  const inflight = useRef<string | undefined>(undefined);  // conversation dont la réponse est en route
  const busyRef = useRef(false);
  busyRef.current = busy;
  useEffect(() => {
    setCid(initialId);
    if (!initialId) {
      ++turn.current;   // nouvelle conversation : l'attente précédente s'arrête (le serveur finit quand même)
      setBusy(false);
      setMessages([]);
      setPending([]);   // les fichiers en attente appartiennent à la discussion quittée
      return;
    }
    // conversation créée à l'instant : l'écran est déjà à jour (et garde ses animations), on ne recharge pas
    if (justCreated.current === initialId) {
      justCreated.current = undefined;
      return;
    }
    setPending([]);
    ++turn.current;   // une autre conversation : l'attente précédente s'arrête
    setBusy(false);
    api.getConversation(initialId).then((c) => {
      setMessages(c.messages || []);
      if (c.working) follow(initialId);   // UniC travaille encore dessus : la réponse arrivera ici
    });
  }, [initialId]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  sendRef.current = (m) => { void send(m); };
  const online = useOnline();
  const [queued, setQueued] = useState(() => readOutbox().length);
  useEffect(() => {   // réseau revenu : on envoie la première demande gardée (les suivantes partent à la fin de chaque réponse)
    if (!online || busy) return;
    const next = takeQueued();
    setQueued(readOutbox().length);
    if (next) {
      setMessages((m) => { const i = m.findIndex((x) => String(x.id).startsWith("q")); return i < 0 ? m : m.filter((_, k) => k !== i); });   // la bulle « en attente » cède la place à l'envoi réel
      setTimeout(() => sendRef.current?.(next), 300);
    }
  }, [online, busy]);
  useEffect(() => {
    if (initialId) return;
    let go: string | null = null;
    try { go = sessionStorage.getItem(AUTO_KEY); sessionStorage.removeItem(AUTO_KEY); } catch { /* ignoré */ }
    if (go) setTimeout(() => sendRef.current?.(go!), 300);
  }, [initialId]);
  const idRef = useRef(initialId);
  idRef.current = initialId;
  useEffect(() => {   // retour dans l'appli : si une réponse était en route, on va la chercher sur le serveur
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      const id = inflight.current || idRef.current;
      if (busyRef.current && id) follow(id);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  useEffect(() => {   // briefing demandé depuis le menu alors que la conversation vide est déjà ouverte
    const onAuto = () => setTimeout(() => {
      if (idRef.current) return;   // changement de conversation : l'effet ci-dessus s'en charge
      let go: string | null = null;
      try { go = sessionStorage.getItem(AUTO_KEY); sessionStorage.removeItem(AUTO_KEY); } catch { /* ignoré */ }
      if (go) sendRef.current?.(go);
    }, 0);
    window.addEventListener("unic:autosend", onAuto);
    return () => window.removeEventListener("unic:autosend", onAuto);
  }, []);
  async function send(override?: string) {
    const msg = (override ?? text).trim();
    if (rec) { setRec(false); import("@capacitor-community/speech-recognition").then((m) => m.SpeechRecognition.stop()).catch(() => {}); }
    if (!msg && pending.length === 0) { setNotice("Écrivez ou dictez un message d'abord."); return; }
    if (busy) return;
    if (!navigator.onLine) {   // sans réseau : texte gardé sur l'appareil, envoyé au retour ; fichiers impossibles
      if (pending.length) { setNotice("Pas de réseau : les fichiers ne peuvent pas partir. Réessayez avec du réseau."); return; }
      const n = queueMessage(msg);
      setText("");
      setMessages((m) => [...m, { id: `q${Date.now()}`, role: "user", content: msg }]);
      setQueued(n);
      setNotice("Pas de réseau : demande gardée, envoyée dès le retour.");
      return;
    }
    const my = ++turn.current;
    setBusy(true);
    setText("");
    const files = pending;
    const abort = new AbortController();
    ctl.current = abort;
    const local: ChatMessage = { id: `u${Date.now()}`, role: "user", content: msg || "Analyse le fichier.", files: files.map((f) => ({ name: f.name, mime: f.type, file: f })) };
    setMessages((m) => [...m, local]);
    setPending([]);   // la carte du fichier quitte la zone de saisie dès l'envoi : elle est déjà dans le message
    let started = false;
    try {
      const file_ids: string[] = [];
      for (const f of files) {
        if (abort.signal.aborted) throw new Stopped();
        setLive({ status: "Préparation du fichier…", text: "" });
        const prep = await prepareFile(f);   // allège avant l'envoi (photos, gros PDF)
        for (const p of prep.files) {
          const up = await api.upload(p);
          file_ids.push(up.id);
        }
        if (prep.note) setNotice("Allégé : " + prep.note);
      }
      setLive({ status: "", text: "" });
      started = true;
      const out = await api.chatStream({ message: msg || "Analyse le fichier.", conversation_id: cid, file_ids, deep }, (ev) => {
        if (ev.t === "conv") inflight.current = ev.conversation_id;
        else if (ev.t === "status") setLive((l) => ({ ...l, status: ev.text || "" }));
        else if (ev.t === "delta") setLive((l) => ({ ...l, text: l.text + (ev.text || "") }));
        else if (ev.t === "reset") setLive((l) => ({ ...l, text: "" }));
      }, abort.signal);
      if (turn.current !== my) return;   // la reprise après coupure a déjà affiché la réponse
      setDeep(false);
      if (!cid) {
        setCid(out.conversation_id);
        justCreated.current = out.conversation_id;
        nav(`/c/${out.conversation_id}`, { replace: true });
      }
      setMessages((m) => [...m, { ...out.message, fresh: !out.streamed }]);   // déjà lu en direct : pas de seconde animation   // le message de l'utilisateur est déjà affiché
    } catch (e: any) {
      if (turn.current !== my) return;
      if (!started) setPending(files);   // le fichier n'a pas pu partir : on le remet pour réessayer
      const id = e instanceof Interrupted ? e.conversationId || cid : undefined;
      if (id) { follow(id); return; }   // le serveur continue : on attend sa réponse
      setMessages((m) => [
        ...m,
        { id: "err", role: "assistant", content: e.message || "Erreur" },
      ]);
    } finally {
      if (turn.current === my) { setBusy(false); inflight.current = undefined; }
    }
  }

  /** Bouton « Arrêter » : coupe la requête, demande l'arrêt au serveur, garde ce qui était déjà fait. */
  function stop() {
    turn.current++;   // la suite de ce tour est ignorée
    ctl.current?.abort();
    const id = inflight.current || idRef.current;
    if (id) api.stopTurn(id).catch(() => {});
    setBusy(false);
    setLive({ status: "", text: "" });
    inflight.current = undefined;
    setMessages((m) => [...m, { id: `stop${Date.now()}`, role: "assistant", content: "⏹ Arrêté à ta demande." }]);
  }

  /** Reprend une réponse que le serveur termine seul (appli quittée, réseau coupé, conversation rouverte). */
  async function follow(id: string) {
    const my = ++turn.current;
    inflight.current = id;
    setBusy(true);
    setLive({ status: "UniC termine le travail…", text: "" });
    if (!idRef.current) { setCid(id); justCreated.current = id; nav(`/c/${id}`, { replace: true }); }
    const until = Date.now() + 20 * 60_000;
    while (turn.current === my && Date.now() < until) {
      try {
        const c = await api.getConversation(id);
        if (turn.current !== my) return;
        if (!c.working) {
          setMessages(c.messages || []);
          break;
        }
      } catch { /* réseau encore absent : on réessaie */ }
      await new Promise((r) => setTimeout(r, 3000));
    }
    if (turn.current === my) { setBusy(false); setLive({ status: "", text: "" }); inflight.current = undefined; }
  }

  async function voice() {
    if (rec) {   // arrêt immédiat côté écran : le plugin ne confirme jamais stop()
      setRec(false);
      import("@capacitor-community/speech-recognition").then((m) => m.SpeechRecognition.stop()).catch(() => {});
      return;
    }
    try {
      if (isNative) {
        const { SpeechRecognition } = await import("@capacitor-community/speech-recognition");
        const { available } = await SpeechRecognition.available();
        if (!available) { setNotice("Reconnaissance vocale absente sur ce téléphone. Utilisez le micro du clavier."); return; }
        const perm = await SpeechRecognition.requestPermissions();
        if (perm.speechRecognition !== "granted") { setNotice("Micro refusé : autorisez-le dans Réglages › Applis › UniC AI › Autorisations."); return; }
        const base = text ? text.trimEnd() + " " : "";
        let heard = false;
        await SpeechRecognition.removeAllListeners();
        await SpeechRecognition.addListener("partialResults", (d: { matches: string[] }) => {
          if (d.matches?.[0]) { heard = true; setText(base + d.matches[0]); }
        });
        // fin de phrase détectée par Android : le micro s'éteint, le texte final arrive juste après
        await SpeechRecognition.addListener("listeningState", (d: { status: "started" | "stopped" }) => {
          if (d.status === "stopped") setTimeout(() => setRec(false), 800);
        });
        setRec(true);
        await SpeechRecognition.start({ language: "fr-FR", partialResults: true, popup: false, maxResults: 1 });
        setTimeout(() => { if (!heard) { setRec(false); setNotice("Je n'ai rien entendu. Parlez plus près, puis réessayez."); } }, 8000);
        return;
      }
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (!SR) { setNotice("Dictée indisponible sur ce navigateur."); return; }
      const recg = new SR();
      recg.lang = "fr-FR";
      recg.onstart = () => setRec(true);
      recg.onend = () => setRec(false);
      recg.onresult = (ev: any) => setText((x) => (x ? x + " " : "") + ev.results[0][0].transcript);
      recg.start();
    } catch (e: any) {
      setRec(false);
      setNotice("Dictée impossible : " + (typeof e === "string" ? e : e?.message || "erreur micro"));
    }
  }

  useEffect(() => {   // « Corriger » depuis l'aperçu d'un document : la consigne arrive dans la barre de saisie
    const onPrefill = (e: Event) => {
      const t = String((e as CustomEvent).detail || "");
      setText(t);
      setTimeout(() => {
        const el = document.querySelector<HTMLTextAreaElement>(".composer textarea");
        el?.focus();
        el?.setSelectionRange(t.length, t.length);
      }, 60);
    };
    window.addEventListener("unic:prefill", onPrefill);
    return () => window.removeEventListener("unic:prefill", onPrefill);
  }, []);
  const [greet, setGreet] = useState<Greeting>(() => pickGreeting());
  useEffect(() => {
    if (messages.length > 0) return;
    const t = setInterval(() => setGreet((g) => pickGreeting(g)), 5600);
    return () => clearInterval(t);
  }, [messages.length]);

  return (
    <>
      <div className="chat" onScroll={(e) => { const c = e.currentTarget; setShowDown(c.scrollHeight - c.scrollTop - c.clientHeight > 260); }}>
        <div className="chat-inner">
          {messages.length === 0 && (
            <div className="hero">
              <GreetingTyper g={greet} />
            </div>
          )}
          {messages.map((m, i) => (
            <MessageView
              key={m.id + i}
              m={m}
              onEdit={(t) => { setText(t); setTimeout(() => { const el = document.querySelector<HTMLTextAreaElement>(".composer textarea"); el?.focus(); el?.setSelectionRange(t.length, t.length); }, 30); }}
              onRegenerate={
                !busy && i === messages.length - 1 && m.role === "assistant" && m.id !== "err"
                  ? () => {
                      const lastUser = [...messages].reverse().find((x) => x.role === "user");
                      if (lastUser) send(lastUser.content);
                    }
                  : undefined
              }
            />
          ))}
          {busy && <Typing deep={deep} web status={live.status} liveHtml={live.text ? md(live.text) : undefined} />}
          <div ref={end} />
        </div>
      </div>
      <div className="composer-wrap">
        {showDown && (
          <button className="scroll-down" aria-label="Aller tout en bas de la conversation" onClick={() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" })}>
            <I.ArrowDown size={20} />
          </button>
        )}
        <QuickChips show={messages.length === 0 && !busy && !text && pending.length === 0} onAsk={(p) => send(p)} />
        <div className="composer">
          <AttachRow items={pending.map((f) => ({ name: f.name, mime: f.type, file: f }))} className="pending"
            onRemove={(i) => setPending((p) => p.filter((_, j) => j !== i))} />
          <textarea
            ref={taRef}
            rows={1}
            placeholder="Écris ou dicte un message…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // téléphone / tablette : « Entrée » du clavier = retour à la ligne ; l'envoi se fait avec la flèche. Ordinateur : Entrée envoie, Maj+Entrée = ligne.
              const touch = isNative || window.matchMedia?.("(pointer: coarse)").matches;
              if (e.key === "Enter" && !e.shiftKey && !touch) {
                e.preventDefault();
                send();
              }
            }}
          />
          <div className="composer-bar">
            <button className="tool round" aria-label="Ajouter du contexte" onClick={() => setSheet(true)}><I.Plus /></button>
            <button className={`mode-chip ${deep ? "on" : ""}`} aria-pressed={deep} onClick={() => setDeep((d) => !d)}
              title="Réflexion profonde (Claude Opus), pour cette question">
              {deep ? <><I.Sparkle size={16} /> Profond</> : "Normal"}
            </button>
            {pending.length > 0 && <span className="grow">{pending.length} fichier(s)</span>}
            {pending.length === 0 && <span className="grow" />}
            <button className={`tool round ${rec ? "rec-on" : ""}`} aria-label={rec ? "Arrêter la dictée" : "Dicter"} onClick={voice}>
              {rec ? <I.Stop /> : <I.Mic />}
            </button>
            <button className={`send round ${busy ? "stop" : ""}`} aria-label={busy ? "Arrêter" : "Envoyer"} onClick={() => (busy ? stop() : send())}>
              {busy ? <I.Stop /> : <I.ArrowUp />}
            </button>
          </div>
          <input
            id="chat-file"
            ref={fileRef}
            className="sr-only"
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.txt,.csv,.png,.jpg,.jpeg,.webp,.dxf,.ifc,.dwg"
            onChange={(e) => { const fs = Array.from(e.target.files || []); e.target.value = ""; setPending((p) => [...p, ...fs]); }}
          />
          <input
            id="chat-photo"
            className="sr-only"
            type="file"
            multiple
            accept="image/*"
            onChange={(e) => { const fs = Array.from(e.target.files || []); e.target.value = ""; setPending((p) => [...p, ...fs]); }}
          />
          <input
            id="chat-cam"
            ref={camRef}
            className="sr-only"
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => { const fs = Array.from(e.target.files || []); e.target.value = ""; setPending((p) => [...p, ...fs]); }}
          />
        </div>
        {(!online || queued > 0) && (
          <div className="toast" role="status">
            {online ? `Envoi de ${queued} demande(s) gardée(s)…` : `Hors ligne${queued ? ` · ${queued} en attente` : ""} : vos demandes écrites partiront au retour du réseau.`}
          </div>
        )}
        {notice && <div className="toast" role="status">{notice}</div>}
      </div>
      {sheet && (
        <div className="sheet-back" onClick={() => setSheet(false)}>
          <div className="sheet" role="dialog" aria-label="Ajouter du contexte" onClick={(e) => e.stopPropagation()}>
            <div className="sheet-grip" />
            <div className="sheet-head"><button className="tool" aria-label="Fermer" onClick={() => setSheet(false)}><I.Close size={20} /></button><b>Ajouter du contexte</b><span /></div>
            <div className="sheet-grid">
              <label htmlFor="chat-cam" className="sheet-btn" onClick={() => setTimeout(() => setSheet(false), 50)}><span><I.Camera /></span>Caméra</label>
              <label htmlFor="chat-photo" className="sheet-btn" onClick={() => setTimeout(() => setSheet(false), 50)}><span><I.Image /></span>Photos</label>
              <label htmlFor="chat-file" className="sheet-btn" onClick={() => setTimeout(() => setSheet(false), 50)}><span><I.File /></span>Fichiers</label>
              <button className={`sheet-btn ${apps ? "on" : ""}`} aria-expanded={apps} onClick={() => setApps((a) => !a)}><span><I.Apps /></span>Plus</button>
            </div>
            {apps
              ? <AppsList onAsk={(p) => send(p)} onClose={() => setSheet(false)} />
              : <p className="hint">Plans, PDF, photos de chantier : l'IA les lit pour répondre.</p>}
          </div>
        </div>
      )}
    </>
  );
}


type DocFilter = { q: string; from: string; to: string; min: string; max: string };
const NO_FILTER: DocFilter = { q: "", from: "", to: "", min: "", max: "" };

function applyDocFilter(rows: any[], f: DocFilter): any[] {
  const q = f.q.trim().toLowerCase();
  const min = f.min === "" ? null : Number(f.min);
  const max = f.max === "" ? null : Number(f.max);
  return rows.filter((r) => {
    if (q) {
      const flat = (t: string) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
      const hay = flat([r.client_name, r.customer_name, r.client_label, r.number, r.title, r.supplier_name, r.kind, r.status].join(" "));
      if (!flat(q).split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    const day = (r.created_at || "").slice(0, 10);
    if (f.from && (!day || day < f.from)) return false;
    if (f.to && (!day || day > f.to)) return false;
    if (min !== null && !(typeof r.total === "number" && r.total >= min)) return false;
    if (max !== null && !(typeof r.total === "number" && r.total <= max)) return false;
    return true;
  });
}

/** Recherche dans une bibliothèque : texte (client, numéro, titre), dates, montants. */
function DocFilters({ value, onChange, count, total, money = true }: {
  value: DocFilter; onChange: (f: DocFilter) => void; count: number; total: number; money?: boolean;
}) {
  const set = (k: keyof DocFilter) => (e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, [k]: e.target.value });
  const active = JSON.stringify(value) !== JSON.stringify(NO_FILTER);
  return (
    <div className="doc-filters">
      <input type="search" placeholder="Rechercher : client, numéro, titre…" value={value.q} onChange={set("q")} aria-label="Rechercher" />
      <div className="doc-filters-row">
        <label>Du <input type="date" value={value.from} onChange={set("from")} /></label>
        <label>Au <input type="date" value={value.to} onChange={set("to")} /></label>
        {money && <label>Min <input type="number" inputMode="numeric" value={value.min} onChange={set("min")} /></label>}
        {money && <label>Max <input type="number" inputMode="numeric" value={value.max} onChange={set("max")} /></label>}
      </div>
      <p className="hint">
        {count} sur {total} document(s)
        {active && <> · <button className="link-btn" onClick={() => onChange(NO_FILTER)}>Effacer</button></>}
      </p>
    </div>
  );
}

function useDocLibrary(load: () => Promise<any[]>) {
  const [rows, setRows] = useState<any[]>([]);
  const [f, setF] = useState<DocFilter>(NO_FILTER);
  useEffect(() => {
    load().then(setRows);
  }, []);
  const shown = applyDocFilter(rows, f);
  return { rows, shown, f, setF };
}

function TablePage({
  title,
  lede,
  columns,
  rows,
  onRow,
  extra,
}: {
  title: string;
  lede?: string;
  columns: string[];
  rows: (string | number | null | undefined)[][];
  onRow?: (i: number) => void;
  extra?: React.ReactNode;
}) {
  return (
    <div className="page">
      <div className="page-inner">
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
        {extra}
        <div className="table-wrap">
          {rows.length === 0 ? (
            <div className="empty">Aucune donnée dans la base UniC. Rien n'est inventé.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} onClick={() => onRow?.(i)} style={{ cursor: onRow ? "pointer" : "default" }}>
                    {r.map((c, j) => (
                      <td key={j} data-label={columns[j]}>{c ?? "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function Clients() {
  const [rows, setRows] = useState<any[]>([]);
  const [name, setName] = useState("");
  const load = () => api.customers().then(setRows);
  useEffect(() => {
    load();
  }, []);
  return (
    <TablePage
      title="Clients"
      lede="Fiches uniquement saisies. Aucun client fictif."
      columns={["Code", "Nom", "Ville", "E-mail", "Tél"]}
      rows={rows.map((c) => [c.code, c.name, c.city, c.email, c.phone])}
      extra={
        <form
          className="toolbar"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!name.trim()) return;
            await api.createCustomer({ name });
            setName("");
            load();
          }}
        >
          <input placeholder="Nouveau client" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn btn-copper">Ajouter</button>
        </form>
      }
    />
  );
}

function Materiaux() {
  const [rows, setRows] = useState<any[]>([]);
  const [sku, setSku] = useState("");
  const [kind, setKind] = useState("selling");
  const [amount, setAmount] = useState("");
  const load = () => api.materials().then(setRows);
  useEffect(() => {
    load();
  }, []);
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Matériaux</h1>
        <p className="lede">Catalogue UniC. Les prix vides restent vides — jamais inventés.</p>
        <form
          className="toolbar"
          onSubmit={async (e) => {
            e.preventDefault();
            const m = rows.find((x) => x.sku === sku);
            if (!m || !amount) return;
            await api.addPrice(m.id, { kind, amount: Number(amount.replace(",", ".")) });
            setAmount("");
            load();
          }}
        >
          <select value={sku} onChange={(e) => setSku(e.target.value)}>
            <option value="">SKU…</option>
            {rows.map((m) => (
              <option key={m.id} value={m.sku}>
                {m.sku}
              </option>
            ))}
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="selling">Vente</option>
            <option value="purchase">Achat</option>
          </select>
          <input placeholder="Montant" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <button className="btn btn-copper">Enregistrer le prix</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Nom</th>
                <th>Unité</th>
                <th>Vente</th>
                <th>Achat</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id}>
                  <td data-label="SKU">{m.sku}</td>
                  <td data-label="Nom">{m.name}</td>
                  <td data-label="Unité">{m.unit}</td>
                  <td data-label="Vente">{m.selling_price ?? "non renseigné"}</td>
                  <td data-label="Achat">{m.purchase_price ?? "non renseigné"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ProjetsManuels() {
  const nav = useNavigate();
  const [rows, setRows] = useState<any[]>([]);
  const [name, setName] = useState("");
  const load = () => api.projects().then(setRows);
  useEffect(() => {
    load();
  }, []);
  return (
    <TablePage
      title="Chantiers / projets"
      lede="Mémoire persistante par projet : devis, factures, documents."
      columns={["Code", "Nom", "Client", "Statut", "Lieu"]}
      rows={rows.map((p) => [p.code, p.name, p.customer_name, p.status, p.location])}
      onRow={(i) => nav(`/chantiers/${rows[i].id}`)}
      extra={
        <form
          className="toolbar"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!name.trim()) return;
            await api.createProject({ name });
            setName("");
            load();
          }}
        >
          <input placeholder="Nouveau chantier" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn btn-copper">Créer</button>
        </form>
      }
    />
  );
}

function ChantierDetail() {
  const { id } = useParams();
  const [p, setP] = useState<any>(null);
  useEffect(() => {
    if (id) api.getProject(id).then(setP);
  }, [id]);
  if (!p) return <div className="page">Chargement…</div>;
  return (
    <div className="page">
      <div className="page-inner">
        <h1>{p.name}</h1>
        <p className="lede">
          {p.code} · {p.status} · Client : {p.customer_name || "non renseigné"} · Lieu : {p.location || "non renseigné"} ·
          Budget : {p.budget ?? "non renseigné"}
        </p>
        <h3>Chantiers</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Statut</th>
                <th>Avancement</th>
              </tr>
            </thead>
            <tbody>
              {(p.sites || []).map((s: any) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.status}</td>
                  <td>{s.progress_pct} %</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>Devis</h3>
        <ul>
          {(p.quotations || []).map((q: any) => (
            <li key={q.id}>
              <Link to={`/devis/${q.id}`}>
                {q.number} — {statusFr(q.status)} — {q.total ?? "total incomplet"}
              </Link>
            </li>
          ))}
        </ul>
        <h3>Factures</h3>
        <ul>
          {(p.invoices || []).map((q: any) => (
            <li key={q.id}>
              <Link to={`/factures/${q.id}`}>
                {q.number} — {statusFr(q.status)} — payé {q.paid}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ExportButtons({ kind }: { kind: "quotes" | "invoices" }) {
  const [err, setErr] = useState("");
  const go = (fmt: "csv" | "xlsx") =>
    downloadAuth(`/api/export/${kind}.${fmt}`, `unic-${kind === "quotes" ? "devis" : "factures"}.${fmt}`).catch((e) => setErr(e?.message || "Export impossible"));
  return (
    <div className="row-actions">
      <button className="btn btn-line btn-small" onClick={() => go("xlsx")}>Exporter Excel</button>
      <button className="btn btn-line btn-small" onClick={() => go("csv")}>Exporter CSV</button>
      {err && <span className="error" role="alert">{err}</span>}
    </div>
  );
}

function DevisList() {
  const nav = useNavigate();
  const { rows, shown, f, setF } = useDocLibrary(api.quotes);
  return (
    <TablePage
      title="Devis"
      lede="Tous les devis de l'IA. Une correction modifie le même devis."
      extra={<><ExportButtons kind="quotes" /><DocFilters value={f} onChange={setF} count={shown.length} total={rows.length} /></>}
      columns={["N°", "Titre", "Client", "Statut", "Total", "Prix complets"]}
      rows={shown.map((q) => [q.number, q.title, q.client_name || q.customer_name || q.client_label, statusFr(q.status), q.total ?? "incomplet", q.prices_complete ? "oui" : "non"])}
      onRow={(i) => nav(`/devis/${shown[i].id}`)}
    />
  );
}

function DocDetail({ kind }: { kind: "quote" | "invoice" | "po" | "dn" }) {
  const { id } = useParams();
  const [d, setD] = useState<any>(null);
  const [showPreview, setShowPreview] = useState(false);
  async function load() {
    if (!id) return;
    const fn = { quote: api.getQuote, invoice: api.getInvoice, po: api.getPo, dn: api.getDn }[kind];
    setD(await fn(id));
  }
  useEffect(() => {
    load();
  }, [id, kind]);
  if (!d) return <div className="page">Chargement…</div>;
  const download = d.download_url
    ? () => downloadAuth(d.download_url, d.filename || `${d.number}.pdf`)
    : d.artifact_id
      ? () => downloadAuth(`/api/artifacts/${d.artifact_id}/download`, `${d.number}.pdf`)
      : null;
  const shareUrl: string | null = d.download_url || (d.artifact_id ? `/api/artifacts/${d.artifact_id}/download` : null);
  return (
    <div className="page">
      <div className="page-inner">
        <div className="doc-head">
          <div>
            <h1>
              {d.number} <Badge s={d.status} />
            </h1>
            <p className="lede">{d.title}</p>
          </div>
          <div className="toolbar">
            {artifactIdOf(d) && (
              <button className="btn btn-line" onClick={() => setShowPreview(true)}><I.Eye size={16} /> Aperçu</button>
            )}
            {download && (
              <button className="btn btn-copper" onClick={download}>
                Télécharger le PDF
              </button>
            )}
            {shareUrl && <ShareButton url={shareUrl} filename={d.filename || `${d.number}.pdf`} text={kind === "quote" ? d.cover_letter || "" : ""} className="btn btn-line" />}
            {kind === "invoice" && d.balance_url && <ShareButton url={d.balance_url} filename={`Reliquat_${d.number}.pdf`} text={d.balance_message || ""} className="btn btn-copper" label="Partager le reliquat" />}
            {kind === "quote" && d.status !== "approved" && (
              <button
                className="btn btn-line"
                onClick={async () => {
                  await api.approveQuote(d.id);
                  load();
                }}
              >
                Approuver
              </button>
            )}
          </div>
        </div>
        {!d.prices_complete && kind === "quote" && (
          <p className="hint">Prix UniC manquants — rien n'a été inventé. Total incomplet.</p>
        )}
        {kind === "quote" && d.status === "approved" && <CoverLetterBox quote={d} url={shareUrl} filename={d.filename || `${d.number}.pdf`} onChanged={load} />}
        {kind === "quote" && <SignaturePanel quoteId={d.id} />}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Désignation</th>
                <th>Qté</th>
                <th>Unité</th>
                {kind !== "dn" && <th>P.U.</th>}
                {kind !== "dn" && <th>Total</th>}
              </tr>
            </thead>
            <tbody>
              {(d.items || []).map((it: any) => (
                <tr key={it.id || it.position}>
                  <td>{it.position}</td>
                  <td>
                    {it.description}
                    {it.formula ? (
                      <div>
                        <code>{it.formula}</code>
                      </div>
                    ) : null}
                  </td>
                  <td>{it.quantity}</td>
                  <td>{it.unit}</td>
                  {kind !== "dn" && <td>{it.unit_price ?? "non renseigné"}</td>}
                  {kind !== "dn" && <td>{it.total ?? "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {d.assumptions && (
          <p className="lede" style={{ marginTop: 16 }}>
            <b>Hypothèses</b>
            <br />
            {d.assumptions}
          </p>
        )}
        {kind === "invoice" && (
          <form
            className="toolbar"
            style={{ marginTop: 16 }}
            onSubmit={async (e) => {
              e.preventDefault();
              const fd = new FormData(e.target as HTMLFormElement);
              await api.payInvoice(d.id, {
                amount: Number(fd.get("amount")),
                method: String(fd.get("method") || ""),
                reference: String(fd.get("reference") || ""),
              });
              load();
            }}
          >
            <input name="amount" placeholder="Paiement reçu" />
            <input name="method" placeholder="Moyen" />
            <input name="reference" placeholder="Référence" />
            <button className="btn btn-copper">Enregistrer un paiement</button>
            <span className="lede">
              Payé {d.paid} · Reste {d.remaining ?? "—"}
            </span>
          </form>
        )}
      </div>
      {showPreview && <PreviewModal kind={kind} d={d} onClose={() => setShowPreview(false)} onChanged={load} onDownload={download} />}
    </div>
  );
}

const fcfa = (n: number) => `${Math.round(n).toLocaleString("fr-FR").replace(/\u202f|\u00a0/g, " ")}`;

/** Impayés : retards d'abord, relance prête à envoyer (WhatsApp, SMS…) par la feuille de partage. */
function UnpaidPanel() {
  const [u, setU] = useState<any>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api.unpaid().then(setU).catch(() => setU(null)); }, []);
  if (!u || (!u.en_retard.length && !u.a_venir.length)) return null;
  const row = (r: any, late: boolean) => (
    <li key={r.numero} className={late ? "late" : ""}>
      <div>
        <b>{r.client}</b> · {r.numero}
        <span>{fcfa(r.reste)} {r.devise} · {late ? `${r.jours_retard} j de retard` : `échéance ${new Date(r.echeance).toLocaleDateString("fr-FR")}`}</span>
      </div>
      <button className="btn btn-line btn-small" onClick={async () => {
        try { await shareText(r.relance, `Relance ${r.numero}`); setMsg(""); } catch (e: any) { if (!/cancel|abort/i.test(String(e?.message))) setMsg(e?.message || "Partage impossible"); }
      }}>Relancer</button>
    </li>
  );
  return (
    <section className="card-box unpaid">
      {u.en_retard.length > 0 && <h3>⚠️ En retard · {fcfa(u.total_retard)} FCFA</h3>}
      <ul>{u.en_retard.map((r: any) => row(r, true))}</ul>
      {u.a_venir.length > 0 && <h3>À venir · {fcfa(u.total_a_venir)} FCFA</h3>}
      <ul>{u.a_venir.slice(0, 5).map((r: any) => row(r, false))}</ul>
      {msg && <p className="error">{msg}</p>}
    </section>
  );
}

function Factures() {
  const nav = useNavigate();
  const { rows, shown, f, setF } = useDocLibrary(api.invoices);
  return (
    <TablePage
      title="Factures"
      extra={<><UnpaidPanel /><ExportButtons kind="invoices" /><DocFilters value={f} onChange={setF} count={shown.length} total={rows.length} /></>}
      columns={["N°", "Type", "Client", "Statut", "Total", "Payé", "Reste"]}
      rows={shown.map((q) => [q.number, q.kind, q.client_name || q.customer_name, statusFr(q.status), q.total, q.paid, q.remaining])}
      onRow={(i) => nav(`/factures/${shown[i].id}`)}
    />
  );
}
function Commandes() {
  const nav = useNavigate();
  const { rows, shown, f, setF } = useDocLibrary(api.pos);
  return (
    <TablePage
      title="Bons de commande"
      extra={<DocFilters value={f} onChange={setF} count={shown.length} total={rows.length} />}
      columns={["N°", "Titre", "Client / fournisseur", "Statut", "Total"]}
      rows={shown.map((q) => [q.number, q.title, q.client_name || q.supplier_name, statusFr(q.status), q.total ?? "incomplet"])}
      onRow={(i) => nav(`/commandes/${shown[i].id}`)}
    />
  );
}
function Livraisons() {
  const nav = useNavigate();
  const { rows, shown, f, setF } = useDocLibrary(api.dns);
  return (
    <TablePage
      title="Bons de livraison"
      extra={<DocFilters value={f} onChange={setF} count={shown.length} total={rows.length} money={false} />}
      columns={["N°", "Titre", "Client", "Statut"]}
      rows={shown.map((q) => [q.number, q.title, q.client_name || q.customer_name, statusFr(q.status)])}
      onRow={(i) => nav(`/livraisons/${shown[i].id}`)}
    />
  );
}

function Documents() {
  const [files, setFiles] = useState<any[]>([]);
  const [emails, setEmails] = useState<any[]>([]);
  useEffect(() => {
    api.files().then(setFiles);
    api.emails().then(setEmails);
  }, []);
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Documents</h1>
        <p className="lede">Fichiers téléversés et brouillons d'e-mails. Envoi réel : NON DISPONIBLE sans SMTP.</p>
        <h3>Fichiers</h3>
        <TablePage
          title=""
          columns={["Fichier", "Type", "Pages", "Statut"]}
          rows={files.map((f) => [f.filename, f.mime_type, f.page_count, f.processing_status])}
        />
        <h3>Brouillons e-mail</h3>
        <ul>
          {emails.map((e) => (
            <li key={e.id}>
              <b>{e.subject}</b> — {e.to || "destinataire manquant"} — {e.status}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

type HubItem = { to: string; title: string; text: string };

const HUB: { title: string; items: HubItem[] }[] = [
  {
    title: "Connecteurs",
    items: [
      { to: "/courrier", title: "Courrier", text: "Boîte mail : lire, comprendre, répondre" },
      { to: "/google", title: "Fiche Google", text: "Publier tous les 4 jours, mots-clés, fiche complète" },
      { to: "/reseaux", title: "Réseaux & avis", text: "Publications, avis Google, site" },
      { to: "/voix", title: "Voix", text: "Écouter les réponses : voix du téléphone, ElevenLabs, ta voix" },
      { to: "/higgsfield", title: "Higgsfield", text: "Créer des images (rendus de pièces, styles) depuis la conversation" },
    ],
  },
  {
    title: "Cerveau de l'IA",
    items: [
      { to: "/memoire", title: "Mémoire", text: "Ce que l'IA a appris de vous" },
      { to: "/journal", title: "Journal", text: "Ce que l'IA a fait, heure par heure" },
      { to: "/couts", title: "Coût de Claude", text: "Crédit restant, coût par message et par jour" },
      { to: "/sante", title: "Moteur & santé", text: "État de l'IA, du serveur, des connecteurs" },
      { to: "/atelier", title: "Atelier", text: "UniC se vérifie, se corrige et crée ses agents" },
      { to: "/pointage", title: "Pointage", text: "Arrivée et départ du chantier, heures travaillées" },
    ],
  },
  {
    title: "Entreprise",
    items: [
      { to: "/parametres/entreprise", title: "Informations société", text: "Nom, coordonnées, TVA, paramètres de calcul" },
      { to: "/materiaux", title: "Matériaux & prix", text: "Grille de prix UniC" },
      { to: "/clients", title: "Clients", text: "Fiches clients" },
    ],
  },
  {
    title: "Documents créés par l'IA",
    items: [
      { to: "/devis", title: "Devis", text: "Tous les devis de l'IA, corrigés sur place" },
      { to: "/factures", title: "Factures", text: "Factures et paiements" },
      { to: "/commandes", title: "Bons de commande", text: "Bibliothèque des bons de commande" },
      { to: "/livraisons", title: "Bons de livraison", text: "Bibliothèque des bons de livraison" },
      { to: "/agenda", title: "Agenda", text: "Visites, métrés, poses, livraisons" },
      { to: "/prospects", title: "Prospects du site", text: "Demandes laissées sur unicplaquiste.com" },
      { to: "/chantiers", title: "Chantiers", text: "Projets et suivi" },
      { to: "/documents", title: "Fichiers reçus", text: "Plans, PDF, photos" },
    ],
  },
];

/** Crédit Claude restant, en tête des Paramètres (touche pour le détail). */
function CreditBadge() {
  const [u, setU] = useState<Usage | null>(null);
  useEffect(() => { net.usage().then(setU).catch(() => {}); }, []);
  return (
    <Link to="/couts" className="credit-badge">
      <span>Crédit Claude</span>
      <b>{u === null ? "…" : u.reste_usd !== null ? `${Math.max(0, u.reste_usd).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} $ restants` : "À renseigner"}</b>
      <i>{u ? `${u.aujourdhui_usd.toLocaleString("fr-FR", { maximumFractionDigits: 3 })} $ aujourd'hui · ${u.messages_total} messages` : ""}</i>
    </Link>
  );
}

/** Apparence (jour / nuit / auto) et briefing quotidien. */
function PrefsCard() {
  const [mode, setMode] = useTheme();
  const [time, setTime] = useState(getBriefingTime() ?? "");
  const [note, setNote] = useState("");
  const opts: { id: ThemeMode; label: string; icon: React.ReactNode }[] = [
    { id: "light", label: "Jour", icon: <I.Sun size={16} /> },
    { id: "dark", label: "Nuit", icon: <I.Moon size={16} /> },
    { id: "auto", label: "Auto", icon: null },
  ];
  const plan = async (t: string | null) => { setTime(t ?? ""); setNote(await scheduleBriefing(t)); };
  return (
    <section className="card-box prefs">
      <label>Apparence</label>
      <div className="seg" role="group" aria-label="Apparence">
        {opts.map((o) => (
          <button key={o.id} className={mode === o.id ? "on" : ""} aria-pressed={mode === o.id} onClick={() => setMode(o.id)}>
            {o.icon}{o.label}
          </button>
        ))}
      </div>
      <label><I.Bell size={14} /> Briefing chaque jour</label>
      <div className="row">
        <input type="time" value={time} onChange={(e) => e.target.value && plan(e.target.value)} aria-label="Heure du briefing" />
        {time && <button className="btn btn-line btn-small" onClick={() => plan(null)}>Désactiver</button>}
      </div>
      <p className="hint">{note || (time ? `Actif chaque jour à ${time.replace(":", " h ")}.` : "Choisis une heure : une notification t'ouvre le briefing.")}</p>
    </section>
  );
}

function SettingsHub() {
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Paramètres</h1>
        <p className="lede">
          Tout se fait dans la conversation. Ici : réglages, connecteurs, consultation.
        </p>
        <CreditBadge />
        <PrefsCard />
        {HUB.map((g) => (
          <section key={g.title}>
            <h3>{g.title}</h3>
            <div className="hub-grid">
              {g.items.map((i) => (
                <Link key={i.to} to={i.to} className="hub-item">
                  <b>{i.title}</b>
                  <span>{i.text}</span>
                </Link>
              ))}
            </div>
          </section>
        ))}
        {(isNative || getCode()) && (
          <section>
            <h3>Session</h3>
            <button className="btn btn-line" onClick={async () => { await signOut(); window.location.reload(); }}>
              Se déconnecter
            </button>
          </section>
        )}
      </div>
    </div>
  );
}

function CompanyPage() {
  const [s, setS] = useState<any>(null);
  useEffect(() => {
    api.settings().then(setS);
  }, []);
  if (!s) return <div className="page">Chargement…</div>;
  function field(k: string, label: string) {
    return (
      <label>
        {label}
        <input
          value={s[k] ?? ""}
          onChange={(e) => setS({ ...s, [k]: e.target.value })}
        />
      </label>
    );
  }
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Paramètres société</h1>
        <p className="lede">Les champs vides restent vides. UniC AI ne complète pas à votre place.</p>
        <div className="form-grid">
          {field("name", "Nom")}
          {field("legal_name", "Raison sociale")}
          {field("address", "Adresse")}
          {field("city", "Ville")}
          {field("country", "Pays")}
          {field("phone", "Téléphone")}
          {field("email", "E-mail")}
          {field("tax_id", "N° fiscal")}
          {field("currency", "Devise")}
          {field("website", "Site")}
          <label>
            TVA (ex. 0.18) — laisser vide si non configurée
            <input
              value={s.vat_rate ?? ""}
              onChange={(e) => setS({ ...s, vat_rate: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </label>
          <label>
            Déchet par défaut
            <input
              value={s.default_waste ?? 0.08}
              onChange={(e) => setS({ ...s, default_waste: Number(e.target.value) })}
            />
          </label>
          <label>
            Échéance des factures (jours après approbation)
            <input type="number" min={0} max={365} value={s.invoice_due_days ?? 15}
              onChange={(e) => setS({ ...s, invoice_due_days: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <label>
            Conditions de paiement
            <textarea value={s.payment_terms || ""} onChange={(e) => setS({ ...s, payment_terms: e.target.value })} />
          </label>
        </div>
        <button
          className="btn btn-copper"
          onClick={async () => {
            await api.saveSettings(s);
            alert("Enregistré");
          }}
        >
          Enregistrer
        </button>
        <AccountCard />
        <SignatureCard />
      </div>
    </div>
  );
}

/** Mon compte : e-mail + mot de passe de connexion, appareils connectés. */
function AccountCard() {
  const [d, setD] = useState<any>(null);
  const [email, setEmail] = useState("");
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api.devices().then((x) => { setD(x); setEmail(x.email || getSavedEmail()); }).catch(() => setD(null));
  useEffect(() => { load(); }, []);
  const save = async () => {
    setMsg("");
    try { await setAccount(email, pw, cur); setCur(""); setPw(""); setMsg("Enregistré. Les autres appareils devront se reconnecter."); load(); }
    catch (e: any) { setMsg(e?.message || "Erreur"); }
  };
  return (
    <section className="card-box account-card">
      <h2>Mon compte</h2>
      <p className="hint">{d?.account ? "Connexion par e-mail et mot de passe active." : "Choisis ton e-mail et ton mot de passe : tu n'auras plus besoin du code d'accès."}</p>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <label>E-mail<input type="email" value={email} autoComplete="username" onChange={(e) => setEmail(e.target.value)} /></label>
        {d?.account && <label>Mot de passe actuel<input type="password" value={cur} autoComplete="current-password" onChange={(e) => setCur(e.target.value)} /></label>}
        <label>{d?.account ? "Nouveau mot de passe" : "Mot de passe"}<input type="password" value={pw} autoComplete="new-password" onChange={(e) => setPw(e.target.value)} /></label>
        <button className="btn btn-copper" type="submit" disabled={!email.trim() || pw.length < 8}>Enregistrer</button>
      </form>
      {msg && <p className="hint">{msg}</p>}
      {d?.devices?.length > 0 && (
        <ul className="backup-list">{d.devices.map((x: any, i: number) => (
          <li key={i}><span>{x.device}</span><span>{x.last_used ? new Date(x.last_used).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</span></li>
        ))}</ul>
      )}
    </section>
  );
}

/** Image de marque (signature, cachet) : photo sur papier blanc, fond retiré, posée sur chaque nouveau document. */
function BrandImageCard({ title, hint, url, upload, remove, alt }: {
  title: string; hint: string; url: string; alt: string; upload: (f: File) => Promise<unknown>; remove: () => Promise<unknown> }) {
  const [src, setSrc] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const load = () => fetchBlobUrl(`${url}?t=${Date.now()}`).then(setSrc).catch(() => setSrc(null));
  useEffect(() => { load(); }, []);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg("");
    try { await fn(); setMsg(ok); await load(); } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  return (
    <section className="card-box sig-card">
      <h2>{title}</h2>
      <p className="hint">{hint}</p>
      <div className="sig-preview">{src ? <img src={src} alt={alt} /> : <span className="hint">Rien d'enregistré.</span>}</div>
      <input ref={ref} type="file" accept="image/*" hidden onChange={(e) => {
        const f = e.target.files?.[0]; e.target.value = "";
        if (f) run(() => upload(f), "Enregistré.");
      }} />
      <div className="row-actions">
        <button className="btn btn-copper" disabled={busy} onClick={() => ref.current?.click()}>{busy ? "Traitement…" : src ? "Remplacer" : "Ajouter"}</button>
        {src && <button className="btn btn-line" disabled={busy} onClick={() => run(remove, "Retiré.")}>Retirer</button>}
      </div>
      {msg && <p className="hint">{msg}</p>}
    </section>
  );
}

function SignatureCard() {
  return (
    <>
      <BrandImageCard title="Ma signature" alt="Ma signature" url="/api/settings/signature" upload={api.uploadSignature} remove={api.deleteSignature}
        hint="Signe en foncé sur une feuille blanche, puis prends-la en photo. Le fond est retiré. Elle apparaît dans le cadre « UniC Plaquiste » des nouveaux devis, factures, bons et reliquats." />
      <BrandImageCard title="Mon cachet" alt="Mon cachet" url="/api/settings/stamp" upload={api.uploadStamp} remove={api.deleteStamp}
        hint="Ton cachet UniC Plaquiste est déjà intégré : il se place à côté de ta signature. Ajoute une photo seulement pour le remplacer (Retirer = retour au cachet intégré)." />
    </>
  );
}

const when = (iso?: string) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "jamais");

/** Sauvegardes : chaque jour sur le serveur et dans la boîte Gmail ; téléchargement et restauration. */
function BackupCard() {
  const [d, setD] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const load = () => api.backups().then(setD).catch((e) => setMsg(e?.message || "Erreur"));
  useEffect(() => { load(); }, []);
  const st = d?.status || {};
  return (
    <section className="card-box backup-card">
      <h2>Sauvegardes</h2>
      <p className="hint">Chaque jour, tout seul : devis, factures, clients, mémoire, signature.
        Gardées sur le serveur (14 dernières) et dans ta boîte Gmail, dossier « {d?.folder || "UniC-Sauvegardes"} » (30 dernières).</p>
      {d && (
        <ul className="backup-status">
          <li>Dernière sauvegarde : <b>{when(st.last_local)}</b></li>
          <li>Copie dans Gmail : <b>{d.offsite ? when(st.last_remote) : "boîte mail non connectée"}</b></li>
          {st.last_verified && !st.verify_error && <li>Relecture de contrôle : <b>✓ restaurable</b> ({when(st.last_verified)})</li>}
          {st.verify_error && <li className="error">Sauvegarde non restaurable : {st.verify_error}</li>}
          {st.last_remote_error && <li className="error">{st.last_remote_error}</li>}
          {st.last_error && <li className="error">{st.last_error}</li>}
        </ul>
      )}
      <div className="row-actions">
        <button className="btn btn-copper" disabled={!!busy} onClick={async () => {
          setBusy("save"); setMsg("");
          try {
            const r = await api.backupNow();
            setMsg(r.offsite?.ok ? "Sauvegardé ici et dans Gmail." : r.offsite?.error ? `Sauvegardé sur le serveur. ${r.offsite.error}` : "Sauvegardé sur le serveur.");
            await load();
          } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(""); }
        }}>{busy === "save" ? "Sauvegarde…" : "Sauvegarder maintenant"}</button>
        <button className="btn btn-line" disabled={!!busy} onClick={() => ref.current?.click()}>Restaurer…</button>
      </div>
      <input ref={ref} type="file" accept=".zip,application/zip" hidden onChange={async (e) => {
        const f = e.target.files?.[0]; e.target.value = "";
        if (!f) return;
        if (!window.confirm(`Remplacer toutes les données par la sauvegarde « ${f.name} » ? Une copie de l'état actuel est faite avant.`)) return;
        setBusy("restore"); setMsg("");
        try { const r = await api.restoreBackup(f); setMsg(`Restauré (sauvegarde du ${when(r.restored_from)}). Copie de sécurité : ${r.safety_backup}.`); await load(); }
        catch (err: any) { setMsg(err?.message || "Erreur"); } finally { setBusy(""); }
      }} />
      {msg && <p className="hint">{msg}</p>}
      {d?.backups?.length > 0 && (
        <ul className="backup-list">
          {d.backups.slice(0, 5).map((b: any) => (
            <li key={b.name}>
              <span>{when(b.created_at)} · {b.size < 1048576 ? `${Math.max(1, Math.round(b.size / 1024))} Ko` : `${(b.size / 1048576).toFixed(1)} Mo`}</span>
              <button className="btn btn-line btn-small" onClick={() => downloadAuth(`/api/backups/${b.name}/download`, b.name)}>Télécharger</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Sante() {
  const [h, setH] = useState<any>(null);
  useEffect(() => {
    api.health().then(setH);
  }, []);
  if (!h) return <div className="page">Chargement…</div>;
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Santé du système</h1>
        <p className="lede">{h.note}</p>
        <BackupCard />
        <div className="health-grid">
          <div className="stat">
            <h3>Application</h3>
            <b>{h.status}</b>
          </div>
          <div className="stat">
            <h3>Base</h3>
            <b>{h.database.status}</b>
            <div>{h.database.url_kind}</div>
          </div>
          <div className="stat">
            <h3>Stockage</h3>
            <b>{h.storage.status}</b>
          </div>
        </div>
        <h3>Fournisseurs IA</h3>
        <ul>
          {h.ai_providers.map((p: any) => (
            <li key={p.id}>
              {p.id} — {p.status} {p.detail ? `— ${p.detail}` : ""}
            </li>
          ))}
        </ul>
        <h3>Capacités</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Description</th>
                <th>État</th>
              </tr>
            </thead>
            <tbody>
              {h.capabilities.map((c: any) => (
                <tr key={c.id}>
                  <td>
                    <code>{c.id}</code>
                  </td>
                  <td>{c.description}</td>
                  <td>
                    {c.available ? (
                      "OK"
                    ) : (
                      <>
                        <span className="na">NON DISPONIBLE</span> {c.reason}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { user, gate, error, check } = useOwner();
  const loc = useLocation();
  const chatMatch = useMatch("/c/:id");
  // la conversation reste montée entre « / » et « /c/:id » : pas de rechargement, animations conservées
  const isChat = loc.pathname === "/" || !!chatMatch;
  // les mails relevés ne survivent pas à la fermeture complète de l'appli (une fois par lancement)
  useEffect(() => {
    if (!user) return;
    try { if (sessionStorage.getItem("unic.boot")) return; sessionStorage.setItem("unic.boot", "1"); } catch { /* ignoré */ }
    net.mailPurge().catch(() => {});
  }, [user]);
  if (gate === "connect") return <Connexion onDone={check} />;
  if (gate === "error")
    return (
      <div className="login">
        <div className="login-card">
          <p className="error">{error}</p>
          <button className="btn btn-copper" onClick={check}>Réessayer</button>
          {isNative && (
            <button className="btn btn-line" onClick={() => { clearConnection(); check(); }}>Changer de serveur</button>
          )}
        </div>
      </div>
    );
  if (gate === "loading" || !user) return <div className="login">Chargement…</div>;
  return (
    <Shell user={user}>
      {isChat ? (
        <Chat initialId={chatMatch?.params.id} />
      ) : (
      <Routes>
        <Route path="/clients" element={<Clients />} />
        <Route path="/materiaux" element={<Materiaux />} />
        <Route path="/chantiers" element={<Chantiers />} />
        <Route path="/chantiers/manuels" element={<ProjetsManuels />} />
        <Route path="/chantiers/:id" element={<ChantierDetail />} />
        <Route path="/devis" element={<DevisList />} />
        <Route path="/devis/:id" element={<DocDetail kind="quote" />} />
        <Route path="/factures" element={<Factures />} />
        <Route path="/agenda" element={<Agenda />} />
        <Route path="/suivi" element={<Suivi />} />
        <Route path="/suivi/:key" element={<SuiviClient />} />
        <Route path="/prospects" element={<Prospects />} />
        <Route path="/factures/:id" element={<DocDetail kind="invoice" />} />
        <Route path="/commandes" element={<Commandes />} />
        <Route path="/commandes/:id" element={<DocDetail kind="po" />} />
        <Route path="/livraisons" element={<Livraisons />} />
        <Route path="/livraisons/:id" element={<DocDetail kind="dn" />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/memoire" element={<Memoire />} />
        <Route path="/voix" element={<Voix />} />
        <Route path="/higgsfield" element={<Higgsfield />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/couts" element={<Couts />} />
        <Route path="/google" element={<FicheGoogle />} />
        <Route path="/courrier" element={<Courrier />} />
        <Route path="/reseaux" element={<Reseaux />} />
        <Route path="/parametres" element={<SettingsHub />} />
        <Route path="/parametres/entreprise" element={<CompanyPage />} />
        <Route path="/sante" element={<Sante />} />
        <Route path="/atelier" element={<Atelier />} />
        <Route path="/pointage" element={<Pointage />} />
        <Route path="/unic" element={<UnicVoice />} />
        <Route path="/interprete" element={<Interpreter />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      )}
    </Shell>
  );
}
