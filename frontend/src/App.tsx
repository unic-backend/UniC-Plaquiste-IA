import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, downloadAuth, getToken, setToken, type ChatMessage, type Conv, type User } from "./api";

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
  let html = esc(text);
  html = html.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^\- (.*)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);
  html = html.replace(/\n\n/g, "</p><p>");
  html = html.replace(/\n/g, "<br/>");
  return `<p>${html}</p>`;
}

function Badge({ s }: { s?: string }) {
  const v = (s || "").toLowerCase();
  return <span className={`badge ${v}`}>{v || "—"}</span>;
}

function MessageView({ m }: { m: ChatMessage }) {
  const structured = m.meta?.structured;
  const arts = m.meta?.artifacts || [];
  return (
    <div className={`msg ${m.role}`}>
      <div className="avatar">{m.role === "user" ? "Vous" : "U"}</div>
      <div className="bubble">
        <div className="md" dangerouslySetInnerHTML={{ __html: md(m.content) }} />
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
        {arts.length ? (
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

function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);
  return { user, setUser, ready };
}

const NAV = [
  { to: "/", label: "Conversation" },
  { to: "/chantiers", label: "Chantiers" },
  { to: "/devis", label: "Devis" },
  { to: "/factures", label: "Factures" },
  { to: "/commandes", label: "Bons de commande" },
  { to: "/livraisons", label: "Bons de livraison" },
  { to: "/clients", label: "Clients" },
  { to: "/fournisseurs", label: "Fournisseurs" },
  { to: "/materiaux", label: "Matériaux" },
  { to: "/documents", label: "Documents" },
  { to: "/parametres", label: "Paramètres" },
];

function Shell({ user, onLogout, children }: { user: User; onLogout: () => void; children: React.ReactNode }) {
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
        <nav className="nav">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={loc.pathname === n.to ? "active" : ""}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="conv-list">
          {convs.map((c) => (
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
        <div className="side-foot">
          <strong>{user.name}</strong>
          {user.email}
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <Link to="/sante" style={{ color: "#d5ddd8" }}>
              Santé
            </Link>
            <button className="btn-ghost" style={{ width: "auto", padding: 0 }} onClick={onLogout}>
              Déconnexion
            </button>
          </div>
        </div>
      </aside>
      <section className="main">
        <div className="topbar">
          <button className="icon-btn" onClick={() => setOpen(true)} aria-label="Menu">
            ☰
          </button>
          <Logo size={22} />
          <b>UniC AI</b>
        </div>
        {children}
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
  const [rec, setRec] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setCid(initialId);
    if (!initialId) {
      setMessages([]);
      return;
    }
    api.getConversation(initialId).then((c) => setMessages(c.messages || []));
  }, [initialId]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(override?: string) {
    const msg = (override ?? text).trim();
    if ((!msg && pending.length === 0) || busy) return;
    setBusy(true);
    setText("");
    const local: ChatMessage = { id: "local", role: "user", content: msg || pending.map((f) => f.name).join(", ") };
    setMessages((m) => [...m, local]);
    try {
      const file_ids: string[] = [];
      for (const f of pending) {
        const up = await api.upload(f);
        file_ids.push(up.id);
      }
      setPending([]);
      const out = await api.chat({ message: msg || "Analyse le fichier.", conversation_id: cid, file_ids });
      if (!cid) {
        setCid(out.conversation_id);
        nav(`/c/${out.conversation_id}`, { replace: true });
      }
      setMessages((m) => [...m.filter((x) => x.id !== "local"), local, out.message]);
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { id: "err", role: "assistant", content: e.message || "Erreur" },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function voice() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      alert("Saisie vocale non disponible sur ce navigateur.");
      return;
    }
    const recg = new SR();
    recg.lang = "fr-FR";
    recg.onstart = () => setRec(true);
    recg.onend = () => setRec(false);
    recg.onresult = (ev: any) => {
      const t = ev.results[0][0].transcript;
      setText((x) => (x ? x + " " + t : t));
    };
    recg.start();
  }

  const suggestions = [
    "Cloison 12 m × 2,50 m, deux faces, 2 portes",
    "Combien de plaques pour 320 m × 2,50 m deux faces ?",
    "Fais le devis",
    "Prépare le rapport de chantier",
  ];

  return (
    <>
      <div className="chat">
        <div className="chat-inner">
          {messages.length === 0 && (
            <div className="hero">
              <h1>UniC AI, à votre service.</h1>
              <p>
                Employé digital d'UniC Plaquiste. Décrivez le besoin, joignez un plan ou une photo de chantier.
                Je calcule, je prépare les documents — je n'invente jamais un prix.
              </p>
              <div className="chips">
                {suggestions.map((s) => (
                  <button key={s} className="chip" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <MessageView key={m.id + i} m={m} />
          ))}
          {busy && (
            <div className="msg assistant">
              <div className="avatar">U</div>
              <div className="bubble">Traitement en cours…</div>
            </div>
          )}
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
            <button className="tool" title="Joindre" onClick={() => fileRef.current?.click()}>
              ＋
            </button>
            <button className="tool" title="Photo chantier" onClick={() => camRef.current?.click()}>
              ⌯
            </button>
            <button className={`tool ${rec ? "rec" : ""}`} title="Voix" onClick={voice}>
              ●
            </button>
            <div className="grow">{pending.length ? `${pending.length} fichier(s)` : "Entrée pour envoyer"}</div>
            <button className="send" onClick={() => send()} disabled={busy}>
              ↑
            </button>
          </div>
          <input
            ref={fileRef}
            hidden
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.txt,.csv,.png,.jpg,.jpeg,.webp"
            onChange={(e) => setPending((p) => [...p, ...Array.from(e.target.files || [])])}
          />
          <input
            ref={camRef}
            hidden
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => setPending((p) => [...p, ...Array.from(e.target.files || [])])}
          />
        </div>
      </div>
    </>
  );
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("marco.r@example.org");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const r = await api.login(email, password);
      setToken(r.token);
      onLogin(r.user);
    } catch (ex: any) {
      setErr(ex.message || "Connexion impossible");
    }
  }
  return (
    <div className="login">
      <div className="login-card">
        <Logo size={40} />
        <h1>UniC AI</h1>
        <p>Plateforme métier d'UniC Plaquiste. Accès réservé.</p>
        <form onSubmit={submit}>
          <label>
            E-mail
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </label>
          <label>
            Mot de passe
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </label>
          {err && <div className="error">{err}</div>}
          <button className="btn btn-copper" type="submit">
            Entrer
          </button>
        </form>
        <p className="hint">
          Premier démarrage : compte admin créé automatiquement. Changez le mot de passe en production. Voir README.
        </p>
      </div>
    </div>
  );
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
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api.quotes().then(setRows);
  }, []);
  return (
    <TablePage
      title="Devis"
      lede="PDF réels, éditables tant qu'ils sont en brouillon."
      columns={["N°", "Titre", "Client", "Statut", "Total", "Prix complets"]}
      rows={rows.map((q) => [q.number, q.title, q.customer_name, q.status, q.total ?? "incomplet", q.prices_complete ? "oui" : "non"])}
      onRow={(i) => nav(`/devis/${rows[i].id}`)}
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
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api.invoices().then(setRows);
  }, []);
  return (
    <TablePage
      title="Factures"
      columns={["N°", "Type", "Client", "Statut", "Total", "Payé", "Reste"]}
      rows={rows.map((q) => [q.number, q.kind, q.customer_name, q.status, q.total, q.paid, q.remaining])}
      onRow={(i) => nav(`/factures/${rows[i].id}`)}
    />
  );
}
function Commandes() {
  const nav = useNavigate();
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api.pos().then(setRows);
  }, []);
  return (
    <TablePage
      title="Bons de commande"
      columns={["N°", "Titre", "Fournisseur", "Statut", "Total"]}
      rows={rows.map((q) => [q.number, q.title, q.supplier_name, q.status, q.total ?? "incomplet"])}
      onRow={(i) => nav(`/commandes/${rows[i].id}`)}
    />
  );
}
function Livraisons() {
  const nav = useNavigate();
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api.dns().then(setRows);
  }, []);
  return (
    <TablePage
      title="Bons de livraison"
      columns={["N°", "Titre", "Client", "Statut"]}
      rows={rows.map((q) => [q.number, q.title, q.customer_name, q.status])}
      onRow={(i) => nav(`/livraisons/${rows[i].id}`)}
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

function SettingsPage() {
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

function ChatRoute() {
  const { id } = useParams();
  return <Chat initialId={id} />;
}

export default function App() {
  const { user, setUser, ready } = useAuth();
  const nav = useNavigate();
  if (!ready) return <div className="login">Chargement…</div>;
  if (!user) return <Login onLogin={(u) => { setUser(u); nav("/"); }} />;
  return (
    <Shell
      user={user}
      onLogout={() => {
        setToken(null);
        setUser(null);
        nav("/login");
      }}
    >
      <Routes>
        <Route path="/" element={<Chat />} />
        <Route path="/c/:id" element={<ChatRoute />} />
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
        <Route path="/parametres" element={<SettingsPage />} />
        <Route path="/sante" element={<Sante />} />
        <Route path="/login" element={<Navigate to="/" />} />
      </Routes>
    </Shell>
  );
}
