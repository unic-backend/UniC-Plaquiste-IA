import { useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useMatch, useNavigate, useParams } from "react-router-dom";
import { Courrier, Journal, Memoire, Reseaux } from "./Reseaux";
import { DraftCards, groupByDate, PageBar, ToolChips, Typing } from "./Chrome";
import * as I from "./Icons";
import { pickGreeting, type Greeting } from "./greetings";
import { api, net, AuthError, clearConnection, downloadAuth, getCode, getServer, isNative, needsServer, saveConnection, type ChatMessage, type Conv, type User } from "./api";

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

function Badge({ s }: { s?: string }) {
  const v = (s || "").toLowerCase();
  return <span className={`badge ${v}`}>{v || "—"}</span>;
}

function fmt(n: number | null | undefined, cur = ""): string {
  if (n === null || n === undefined) return "—";
  return `${new Intl.NumberFormat("fr-FR").format(n)}${cur ? ` ${cur}` : ""}`;
}

const DOC_LABEL: Record<string, string> = { quote: "Devis", invoice: "Facture", po: "Bon de commande", dn: "Bon de livraison" };

/** Document affiché directement dans la conversation (lignes, total, actions). */
function DocCard({ kind, id }: { kind: "quote" | "invoice" | "po" | "dn"; id: string }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
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
  return (
    <div className="doc-card">
      <div className="doc-card-head">
        <div>
          <b>{DOC_LABEL[kind]} {d.number}</b>
          <div className="hint">{d.customer_name || d.client_label ? `Client : ${d.customer_name || d.client_label} · ` : ""}{d.title}</div>
        </div>
        <Badge s={d.status} />
      </div>
      {d.object_text && <p className="hint">{d.object_text}</p>}
      <div className="doc-lines">
        {(d.items || []).map((it: any) => (
          <div className="doc-line" key={it.id || it.position}>
            <div className="doc-line-main">
              <span>{it.description}</span>
              <span className="doc-qty">{it.quantity} {it.unit}</span>
            </div>
            {priced && (
              <div className="doc-line-price">
                <span>{it.unit_price === null || it.unit_price === undefined ? "prix non renseigné" : `${fmt(it.unit_price)} / u.`}</span>
                <b>{fmt(it.total)}</b>
              </div>
            )}
          </div>
        ))}
      </div>
      {priced && (
        <div className="doc-totals">
          {d.subtotal !== null && d.subtotal !== undefined && d.vat_amount ? <div><span>Sous-total</span><span>{fmt(d.subtotal, cur)}</span></div> : null}
          {d.vat_amount ? <div><span>TVA</span><span>{fmt(d.vat_amount, cur)}</span></div> : null}
          <div className="doc-total"><span>Total</span><b>{d.total === null || d.total === undefined ? "incomplet" : fmt(d.total, cur)}</b></div>
          {kind === "quote" && Array.isArray(d.price_check) && (
            d.price_check.length === 0
              ? <p className="hint ic"><I.Check size={16} /> Prix et totaux conformes à la grille</p>
              : <p className="error ic"><I.Alert size={16} /> {d.price_check.length} anomalie(s) : {d.price_check.map((x: any) => `${x.ligne} (attendu ${x.attendu}, trouvé ${x.trouve})`).join(" ; ")}</p>
          )}
          {kind === "quote" && d.prices_complete === false && (
            <p className="hint">Prix manquants sur certaines lignes : rien n'est inventé, le total est partiel.</p>
          )}
        </div>
      )}
      <div className="toolbar">
        {dl && <button className="btn btn-copper btn-small" onClick={dl}>Télécharger le PDF</button>}
        {kind === "quote" && d.status !== "approved" && (
          <button className="btn btn-line btn-small" onClick={async () => { await api.approveQuote(d.id); load(); }}>Approuver</button>
        )}
        <Link className="btn btn-ghost btn-small" to={`/${{ quote: "devis", invoice: "factures", po: "commandes", dn: "livraisons" }[kind]}/${d.id}`}>Détail</Link>
        {d.status === "draft" && (
          <button className="btn btn-ghost btn-small"
            onClick={async () => {
              if (!window.confirm("Retirer ce brouillon de la bibliothèque ?")) return;
              try { await net.discardDoc(kind, d.id); setD(null); setErr("Brouillon retiré."); } catch (e: any) { setErr(e.message); }
            }}>
            Retirer
          </button>
        )}
      </div>
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
  const tw = useReveal(m.content.length, !!m.fresh && m.role === "assistant");
  const html = m.role === "assistant" && m.fresh && !tw.done ? revealHtml(md(m.content)) : md(m.content);
  const structured = m.meta?.structured;
  const arts = m.meta?.artifacts || [];
  return (
    <div className={`msg ${m.role} enter`}>
      <div className="avatar">{m.role === "user" ? "Vous" : "U"}</div>
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
            {onRegenerate && tw.done && <button onClick={onRegenerate}><I.Refresh size={15} /> Régénérer</button>}
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
  const [server, setServer] = useState(getServer());
  const [code, setCode] = useState(getCode());
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    setMsg("");
    const url = server.trim();
    if (isNative && !/^https:\/\/[^\s/]+/i.test(url)) {
      setMsg("Adresse invalide : elle doit commencer par https://");
      setBusy(false);
      return;
    }
    saveConnection(isNative ? url : "", code);
    try {
      await api.me();
      onDone();
    } catch (e: any) {
      setMsg(e instanceof AuthError ? "Code d'accès incorrect." : e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <div className="login-card">
        <h1>UniC AI</h1>
        <p className="hint">{isNative ? "Connectez l'application à votre serveur UniC." : "Code d'accès requis."}</p>
        {isNative && (
          <>
            <label>Adresse du serveur</label>
            <input value={server} placeholder="https://unic.exemple.com" autoCapitalize="none" autoCorrect="off"
              inputMode="url" onChange={(e) => setServer(e.target.value)} />
          </>
        )}
        <label>Code d'accès</label>
        <input type="password" value={code} autoComplete="current-password" onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()} />
        {msg && <p className="error">{msg}</p>}
        <button className="btn btn-copper" disabled={busy || (isNative && !server.trim())} onClick={go}>
          {busy ? "Connexion…" : "Se connecter"}
        </button>
      </div>
    </div>
  );
}


function Shell({ user, children }: { user: User; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [convs, setConvs] = useState<Conv[]>([]);
  const [q, setQ] = useState("");
  const loc = useLocation();
  useEffect(() => {
    api.conversations(q).then(setConvs).catch(() => setConvs([]));
  }, [q, loc.pathname]);
  useEffect(() => setOpen(false), [loc.pathname]);
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
        <input
          placeholder="Rechercher…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ background: "#24302c", color: "#efeae2", borderColor: "#3d4a45" }}
        />
        <div className="conv-list">
          {convs.length === 0 && <div className="conv-empty">{q ? "Aucun résultat." : "Aucune conversation pour l'instant."}</div>}
          {groupByDate(convs).map((g) => (
            <div key={g.label}>
              <div className="conv-label">{g.label}</div>
              {g.rows.map((c) => (
                <div className="conv-item" key={c.id}>
                  <Link to={`/c/${c.id}`} className={loc.pathname === `/c/${c.id}` ? "active" : ""}>
                    {c.title}
                  </Link>
                  <button
                    title="Supprimer"
                    onClick={async () => {
                      await api.deleteConversation(c.id);
                      setConvs((x) => x.filter((i) => i.id !== c.id));
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          ))}
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
  const [pending, setPending] = useState<File[]>([]);
  const [deep, setDeep] = useState(false);
  const [rec, setRec] = useState(false);
  const [sheet, setSheet] = useState(false);
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
  const end = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);

  const justCreated = useRef<string | undefined>(undefined);
  useEffect(() => {
    setCid(initialId);
    if (!initialId) {
      setMessages([]);
      return;
    }
    // conversation créée à l'instant : l'écran est déjà à jour (et garde ses animations), on ne recharge pas
    if (justCreated.current === initialId) {
      justCreated.current = undefined;
      return;
    }
    api.getConversation(initialId).then((c) => setMessages(c.messages || []));
  }, [initialId]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(override?: string) {
    const msg = (override ?? text).trim();
    if (rec) { setRec(false); import("@capacitor-community/speech-recognition").then((m) => m.SpeechRecognition.stop()).catch(() => {}); }
    if (!msg && pending.length === 0) { setNotice("Écrivez ou dictez un message d'abord."); return; }
    if (busy) return;
    setBusy(true);
    setText("");
    const local: ChatMessage = { id: `u${Date.now()}`, role: "user", content: msg || pending.map((f) => f.name).join(", ") };
    setMessages((m) => [...m, local]);
    try {
      const file_ids: string[] = [];
      for (const f of pending) {
        const up = await api.upload(f);
        file_ids.push(up.id);
      }
      setPending([]);
      const out = await api.chat({ message: msg || "Analyse le fichier.", conversation_id: cid, file_ids, deep });
      setDeep(false);
      if (!cid) {
        setCid(out.conversation_id);
        justCreated.current = out.conversation_id;
        nav(`/c/${out.conversation_id}`, { replace: true });
      }
      setMessages((m) => [...m, { ...out.message, fresh: true }]);   // le message de l'utilisateur est déjà affiché
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { id: "err", role: "assistant", content: e.message || "Erreur" },
      ]);
    } finally {
      setBusy(false);
    }
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

  const [greet, setGreet] = useState<Greeting>(() => pickGreeting());
  useEffect(() => {
    if (messages.length > 0) return;
    const t = setInterval(() => setGreet((g) => pickGreeting(g)), 5600);
    return () => clearInterval(t);
  }, [messages.length]);

  return (
    <>
      <div className="chat">
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
          {busy && <Typing deep={deep} web />}
          <div ref={end} />
        </div>
      </div>
      <div className="composer-wrap">
        <div className="composer">
          {pending.length > 0 && (
            <div className="files-pending">
              {pending.map((f, i) => (
                <span className="file-chip" key={i}>
                  {f.name}
                </span>
              ))}
            </div>
          )}
          <textarea
            rows={1}
            placeholder="Écrire un message… « Analyse ce plan », « Fais le devis »"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
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
            <button className="send round" aria-label="Envoyer" onClick={() => send()} disabled={busy}>
              <I.ArrowUp />
            </button>
          </div>
          <input
            id="chat-file"
            ref={fileRef}
            className="sr-only"
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.txt,.csv,.png,.jpg,.jpeg,.webp"
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
            </div>
            <p className="hint">Plans, PDF, photos de chantier : l'IA les lit pour répondre.</p>
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
      const hay = [r.number, r.title, r.customer_name, r.client_label, r.supplier_name, r.kind, r.status].join(" ").toLowerCase();
      if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
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
                      <td key={j}>{c ?? "—"}</td>
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

function Fournisseurs() {
  const [rows, setRows] = useState<any[]>([]);
  const [name, setName] = useState("");
  const load = () => api.suppliers().then(setRows);
  useEffect(() => {
    load();
  }, []);
  return (
    <TablePage
      title="Fournisseurs"
      columns={["Code", "Nom", "E-mail", "Tél"]}
      rows={rows.map((c) => [c.code, c.name, c.email, c.phone])}
      extra={
        <form
          className="toolbar"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!name.trim()) return;
            await api.createSupplier({ name });
            setName("");
            load();
          }}
        >
          <input placeholder="Nouveau fournisseur" value={name} onChange={(e) => setName(e.target.value)} />
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
                  <td>{m.sku}</td>
                  <td>{m.name}</td>
                  <td>{m.unit}</td>
                  <td>{m.selling_price ?? "non renseigné"}</td>
                  <td>{m.purchase_price ?? "non renseigné"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Chantiers() {
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
                {q.number} — {q.status} — {q.total ?? "total incomplet"}
              </Link>
            </li>
          ))}
        </ul>
        <h3>Factures</h3>
        <ul>
          {(p.invoices || []).map((q: any) => (
            <li key={q.id}>
              <Link to={`/factures/${q.id}`}>
                {q.number} — {q.status} — payé {q.paid}
              </Link>
            </li>
          ))}
        </ul>
      </div>
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
      extra={<DocFilters value={f} onChange={setF} count={shown.length} total={rows.length} />}
      columns={["N°", "Titre", "Client", "Statut", "Total", "Prix complets"]}
      rows={shown.map((q) => [q.number, q.title, q.customer_name || q.client_label, q.status, q.total ?? "incomplet", q.prices_complete ? "oui" : "non"])}
      onRow={(i) => nav(`/devis/${shown[i].id}`)}
    />
  );
}

function DocDetail({ kind }: { kind: "quote" | "invoice" | "po" | "dn" }) {
  const { id } = useParams();
  const [d, setD] = useState<any>(null);
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
            {download && (
              <button className="btn btn-copper" onClick={download}>
                Télécharger le PDF
              </button>
            )}
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
    </div>
  );
}

function Factures() {
  const nav = useNavigate();
  const { rows, shown, f, setF } = useDocLibrary(api.invoices);
  return (
    <TablePage
      title="Factures"
      extra={<DocFilters value={f} onChange={setF} count={shown.length} total={rows.length} />}
      columns={["N°", "Type", "Client", "Statut", "Total", "Payé", "Reste"]}
      rows={shown.map((q) => [q.number, q.kind, q.customer_name, q.status, q.total, q.paid, q.remaining])}
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
      columns={["N°", "Titre", "Fournisseur", "Statut", "Total"]}
      rows={shown.map((q) => [q.number, q.title, q.supplier_name, q.status, q.total ?? "incomplet"])}
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
      rows={shown.map((q) => [q.number, q.title, q.customer_name, q.status])}
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
      { to: "/reseaux", title: "Réseaux & Google", text: "Publications, avis, fiche Google, site" },
    ],
  },
  {
    title: "Cerveau de l'IA",
    items: [
      { to: "/memoire", title: "Mémoire", text: "Ce que l'IA a appris de vous" },
      { to: "/journal", title: "Journal", text: "Ce que l'IA a fait, heure par heure" },
      { to: "/sante", title: "Moteur & santé", text: "État de l'IA, du serveur, des connecteurs" },
    ],
  },
  {
    title: "Entreprise",
    items: [
      { to: "/parametres/entreprise", title: "Informations société", text: "Nom, coordonnées, TVA, paramètres de calcul" },
      { to: "/materiaux", title: "Matériaux & prix", text: "Grille de prix UniC" },
      { to: "/clients", title: "Clients", text: "Fiches clients" },
      { to: "/fournisseurs", title: "Fournisseurs", text: "Fiches fournisseurs" },
    ],
  },
  {
    title: "Documents créés par l'IA",
    items: [
      { to: "/devis", title: "Devis", text: "Tous les devis de l'IA, corrigés sur place" },
      { to: "/factures", title: "Factures", text: "Factures et paiements" },
      { to: "/commandes", title: "Bons de commande", text: "Bibliothèque des bons de commande" },
      { to: "/livraisons", title: "Bons de livraison", text: "Bibliothèque des bons de livraison" },
      { to: "/chantiers", title: "Chantiers", text: "Projets et suivi" },
      { to: "/documents", title: "Fichiers reçus", text: "Plans, PDF, photos" },
    ],
  },
];

function SettingsHub() {
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Paramètres</h1>
        <p className="lede">
          Vous n'avez pas besoin d'ouvrir ces pages pour travailler : dites à l'IA ce que vous voulez
          (« fais le devis », « crée le bon de commande », « montre mes devis »). Ici : réglages, connecteurs et consultation.
        </p>
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
            <button className="btn btn-line" onClick={() => { clearConnection(); window.location.reload(); }}>
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
      </div>
    </div>
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
        <Route path="/fournisseurs" element={<Fournisseurs />} />
        <Route path="/materiaux" element={<Materiaux />} />
        <Route path="/chantiers" element={<Chantiers />} />
        <Route path="/chantiers/:id" element={<ChantierDetail />} />
        <Route path="/devis" element={<DevisList />} />
        <Route path="/devis/:id" element={<DocDetail kind="quote" />} />
        <Route path="/factures" element={<Factures />} />
        <Route path="/factures/:id" element={<DocDetail kind="invoice" />} />
        <Route path="/commandes" element={<Commandes />} />
        <Route path="/commandes/:id" element={<DocDetail kind="po" />} />
        <Route path="/livraisons" element={<Livraisons />} />
        <Route path="/livraisons/:id" element={<DocDetail kind="dn" />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/memoire" element={<Memoire />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/courrier" element={<Courrier />} />
        <Route path="/reseaux" element={<Reseaux />} />
        <Route path="/parametres" element={<SettingsHub />} />
        <Route path="/parametres/entreprise" element={<CompanyPage />} />
        <Route path="/sante" element={<Sante />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      )}
    </Shell>
  );
}
