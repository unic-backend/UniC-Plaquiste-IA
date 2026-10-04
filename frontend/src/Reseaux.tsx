import * as I from "./Icons";
import { useEffect, useState } from "react";
import { net, type JournalRow, type MemConflict, type MemState, type Memo, type GProfile, type GReview, type Mail, type MailDraft, type Platform, type Post } from "./api";

const STATUS: Record<string, string> = { draft: "Brouillon", review: "En revue", approved: "Approuvé", published: "Publié" };
const NEXT: Record<string, string> = { draft: "Passer en revue", review: "Approuver", approved: "Marquer publié (manuel)" };

function useToast() {
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), 3500);
    return () => clearTimeout(t);
  }, [msg]);
  return { msg, say: setMsg };
}

async function copy(text: string, say: (m: string) => void) {
  try {
    await navigator.clipboard.writeText(text);
    say("Texte copié.");
  } catch {
    say("Copie impossible : sélectionnez le texte.");
  }
}

function GoogleFiche({ say, onDraft }: { say: (m: string) => void; onDraft: () => void }) {
  const [st, setSt] = useState<{ configured: boolean; missing: string[]; ai: boolean } | null>(null);
  const [prof, setProf] = useState<GProfile | null>(null);
  const [reviews, setReviews] = useState<GReview[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    net.gStatus().then(setSt).catch((e) => say(e.message));
  }, []);

  const load = async () => {
    setBusy(true);
    try {
      setProf(await net.gProfile());
      setReviews(await net.gReviews());
    } catch (e: any) {
      say(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!st) return null;
  if (!st.configured)
    return (
      <section className="card-box">
        <h3>Fiche Google — connexion</h3>
        <p className="hint">NON DISPONIBLE. Variables manquantes sur le serveur :</p>
        <pre className="plan">{st.missing.join("\n")}</pre>
        <p className="hint">Voir le guide « Connecter la fiche Google » dans le README. En attendant : brouillons + copier/coller.</p>
      </section>
    );
  return (
    <section className="card-box">
      <h3>Fiche Google</h3>
      <div className="toolbar">
        <button className="btn btn-copper" disabled={busy} onClick={load}>Charger fiche et avis</button>
      </div>
      {prof && (
        <div>
          <p><b>{prof.title}</b> {prof.phone && `· ${prof.phone}`} {prof.website && `· ${prof.website}`}</p>
          {prof.complete ? <p className="hint">Fiche complète.</p> : (
            <>
              <p className="hint">À améliorer (constaté sur votre fiche) :</p>
              <ul>{prof.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
            </>
          )}
        </div>
      )}
      {reviews.map((r) => (
        <div key={r.id} className="card-box">
          <p><b>{r.author}</b> · {"★".repeat(r.stars)}{"☆".repeat(5 - r.stars)} {r.replied && <span className="badge">Répondu</span>}</p>
          <p className="post-body">{r.comment || "(note sans commentaire)"}</p>
          {!r.replied && (
            <button className="btn btn-line btn-small" disabled={busy || !st.ai}
              onClick={async () => {
                setBusy(true);
                try {
                  await net.gReplyDraft(r.id, { comment: r.comment || `Avis ${r.stars} étoiles sans commentaire`, stars: r.stars });
                  say("Réponse proposée : voir les brouillons.");
                  onDraft();
                } catch (e: any) {
                  say(e.message);
                } finally {
                  setBusy(false);
                }
              }}>
              {st.ai ? "Proposer une réponse" : "IA non disponible"}
            </button>
          )}
        </div>
      ))}
    </section>
  );
}

export function Reseaux() {
  const [plats, setPlats] = useState<Platform[]>([]);
  const [note, setNote] = useState("");
  const [ai, setAi] = useState(false);
  const [sel, setSel] = useState("linkedin");
  const [posts, setPosts] = useState<Post[]>([]);
  const [handle, setHandle] = useState("");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("#UniC #Plaquisterie #BTP #Senegal");
  const [topic, setTopic] = useState("");
  const [comment, setComment] = useState("");
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const { msg, say } = useToast();

  const load = () => {
    net.platforms().then((r) => {
      setPlats(r.platforms);
      setNote(r.auto_publish_note);
      setAi(r.ai_available);
    }).catch((e) => say(e.message));
    net.posts().then(setPosts).catch((e) => say(e.message));
  };
  useEffect(load, []);

  const p = plats.find((x) => x.id === sel);
  useEffect(() => {
    setHandle(p?.handle ?? "");
    setUrl(p?.page_url ?? "");
  }, [sel, plats.length]);

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      if (ok) say(ok);
    } catch (e: any) {
      say(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!p) return <div className="page">Chargement…</div>;
  const full = body + (tags ? `\n\n${tags}` : "");
  const label = (id: string) => plats.find((x) => x.id === id)?.label ?? id;

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Réseaux, fiche Google & site</h1>
        <p className="lede">{note}</p>
        <div className="plat-grid">
          {plats.map((x) => (
            <button key={x.id} className={`plat ${x.id === sel ? "on" : ""}`} onClick={() => setSel(x.id)}>
              <b>{x.label}</b>
              <span>{x.linked ? <><I.Dot size={12} /> Profil enregistré</> : <><I.Circle size={12} /> Non renseigné</>}</span>
            </button>
          ))}
        </div>

        <div className="two-col">
          <section className="card-box">
            <h3>Profil {p.label}</h3>
            <p className="hint">{p.description}</p>
            <label>Identifiant / @handle</label>
            <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@unicplaquiste" />
            <label>URL de la page</label>
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
            <div className="toolbar">
              <button className="btn btn-copper" disabled={busy}
                onClick={() => run(async () => { await net.setAccount(p.id, { handle, page_url: url, linked: true }); load(); }, "Profil enregistré.")}>
                Enregistrer
              </button>
              <button className="btn btn-line" disabled={busy}
                onClick={() => run(async () => { await net.setAccount(p.id, { handle: "", page_url: "", linked: false }); load(); }, "Profil retiré.")}>
                Retirer
              </button>
            </div>
            <p className="hint">Enregistre le profil UniC. Ce n'est pas une connexion API : rien n'est publié automatiquement.</p>
          </section>

          <section className="card-box">
            <h3>Rédiger pour {p.label}</h3>
            <p className="hint">{p.tip}</p>
            <label>Sujet (l'IA rédige à partir de faits que vous donnez)</label>
            <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Ex. cloison terminée à Diamniadio" />
            <label>Avis / commentaire à répondre (optionnel)</label>
            <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
            <div className="toolbar">
              <button className="btn btn-line" disabled={busy || (!topic && !comment)}
                onClick={() => run(async () => {
                  const r = await net.generate({ platform: p.id, topic, comment, details: body });
                  setBody(r.text);
                  if (r.warning) say(r.warning);
                })}>
                {ai ? "Rédiger avec l'IA" : "IA non disponible"}
              </button>
            </div>
            <label>Titre (optionnel)</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
            <label>Texte</label>
            <textarea rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
            <div className={`hint ${full.length > p.max_chars ? "error" : ""}`}>{full.length}/{p.max_chars}</div>
            <label>Hashtags</label>
            <input value={tags} onChange={(e) => setTags(e.target.value)} />
            <div className="toolbar">
              <button className="btn btn-copper" disabled={busy || !body.trim()}
                onClick={() => run(async () => {
                  await net.createPost({ platform: p.id, kind: comment ? "reply" : "post", title, body, hashtags: tags, in_reply_to: comment });
                  setBody(""); setTitle(""); setComment(""); setTopic("");
                  load();
                }, "Brouillon enregistré.")}>
                Enregistrer le brouillon
              </button>
            </div>
          </section>
        </div>

        {sel === "google_business" && <GoogleFiche say={say} onDraft={load} />}

        <section className="card-box">
          <h3>Booster ({p.label})</h3>
          <p className="hint">Plan de conseils pour gagner en visibilité. Aucune action lancée, aucun budget dépensé.</p>
          <button className="btn btn-line" disabled={busy || !ai}
            onClick={() => run(async () => setPlan((await net.boost({ target: p.label, facts: `Profil : ${p.handle || "non renseigné"} ${p.page_url}` })).plan))}>
            {ai ? "Générer le plan" : "IA non disponible"}
          </button>
          {plan && <pre className="plan">{plan}</pre>}
        </section>

        <h2>Brouillons & file d'attente</h2>
        {posts.length === 0 && <div className="empty">Aucun brouillon.</div>}
        {posts.map((d) => (
          <article key={d.id} className="card-box">
            <div className="toolbar">
              <b>{label(d.platform)} · {d.kind === "reply" ? "Réponse" : "Post"} · {STATUS[d.status] ?? d.status}</b>
            </div>
            {d.in_reply_to && <p className="hint">En réponse à : « {d.in_reply_to.slice(0, 200)} »</p>}
            {d.title && <p className="hint">{d.title}</p>}
            <p className="post-body">{d.body}</p>
            {d.hashtags && <p className="hint">{d.hashtags}</p>}
            <div className="toolbar">
              {NEXT[d.status] && (
                <button className="btn btn-copper btn-small" disabled={busy}
                  onClick={() => run(async () => { await net.advance(d.id); load(); })}>
                  {NEXT[d.status]}
                </button>
              )}
              {d.platform === "google_business" && d.status === "approved" && (
                <button className="btn btn-copper btn-small" disabled={busy}
                  onClick={() => run(async () => { await net.publish(d.id); load(); }, "Publié sur la fiche Google.")}>
                  Publier sur Google
                </button>
              )}
              <button className="btn btn-line btn-small" onClick={() => copy(`${d.body}${d.hashtags ? `\n\n${d.hashtags}` : ""}`, say)}>Copier</button>
              <button className="btn btn-ghost btn-small" disabled={busy}
                onClick={() => run(async () => { await net.deletePost(d.id); load(); })}>Supprimer</button>
            </div>
          </article>
        ))}
        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    </div>
  );
}

export function Courrier() {
  const [status, setStatus] = useState<{ read: boolean; send: boolean; ai: boolean; note: string } | null>(null);
  const [mails, setMails] = useState<Mail[]>([]);
  const [open, setOpen] = useState<Mail | null>(null);
  const [info, setInfo] = useState<{ priority?: string; action?: string }>({});
  const [draft, setDraft] = useState<MailDraft | null>(null);
  const [instr, setInstr] = useState("");
  const [busy, setBusy] = useState(false);
  const { msg, say } = useToast();

  const load = () => net.mails().then(setMails).catch((e) => say(e.message));
  useEffect(() => {
    net.mailStatus().then(setStatus).catch((e) => say(e.message));
    load();
  }, []);

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      if (ok) say(ok);
    } catch (e: any) {
      say(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!status) return <div className="page">Chargement…</div>;
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Courrier</h1>
        <p className="lede">
          {status.read ? "Lecture seule : vos mails ne sont ni modifiés ni marqués lus." : status.note}
          {" "}Rien ne part sans votre approbation.
        </p>
        <div className="toolbar">
          <button className="btn btn-copper" disabled={busy || !status.read}
            onClick={() => run(async () => { const r = await net.mailSync(); await load(); say(`${r.new} nouveau(x) mail(s).`); })}>
            Relever la boîte
          </button>
        </div>
        {mails.length === 0 && <div className="empty">Aucun mail relevé.</div>}
        <div className="two-col">
          <div>
            {mails.map((m) => (
              <button key={m.id} className={`plat mail ${open?.id === m.id ? "on" : ""}`}
                onClick={() => { setOpen(m); setInfo({}); setDraft(null); }}>
                <b>{m.subject || "(sans objet)"}</b>{m.suspect && <span className="badge" title="Contient des consignes suspectes : ignorées par l'IA"> <I.Alert size={12} /> suspect</span>}
                <span>{m.from_addr}{m.category ? ` · ${m.category}` : ""}</span>
              </button>
            ))}
          </div>
          {open && (
            <section className="card-box">
              <h3>{open.subject}</h3>
              <p className="hint">De : {open.from_addr} · {open.date}</p>
              {open.summary && <p><b>Résumé :</b> {open.summary}</p>}
              {info.action && <p><b>Action conseillée :</b> {info.action} {info.priority ? `(priorité ${info.priority})` : ""}</p>}
              <pre className="plan">{open.body}</pre>
              <div className="toolbar">
                <button className="btn btn-line" disabled={busy || !status.ai}
                  onClick={() => run(async () => {
                    const r = await net.analyze(open.id);
                    setInfo({ priority: r.priority, action: r.action });
                    setOpen(r);
                    load();
                  })}>
                  {status.ai ? "Comprendre" : "IA non disponible"}
                </button>
              </div>
              <label>Consigne pour la réponse (optionnel)</label>
              <input value={instr} onChange={(e) => setInstr(e.target.value)} placeholder="Ex. proposer une visite jeudi" />
              <div className="toolbar">
                <button className="btn btn-copper" disabled={busy || !status.ai}
                  onClick={() => run(async () => setDraft(await net.replyDraft(open.id, instr)), "Réponse proposée.")}>
                  Proposer une réponse
                </button>
              </div>
              {draft && (
                <div>
                  <label>À</label>
                  <input value={draft.to_addr} disabled={draft.status !== "draft"} onChange={(e) => setDraft({ ...draft, to_addr: e.target.value })} />
                  <label>Objet</label>
                  <input value={draft.subject} disabled={draft.status !== "draft"} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
                  <label>Message</label>
                  <textarea rows={8} value={draft.body} disabled={draft.status !== "draft"} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
                  <div className="toolbar">
                    {draft.status === "draft" && (
                      <button className="btn btn-copper" disabled={busy}
                        onClick={() => run(async () => {
                          await net.editDraft(draft.id, { to_addr: draft.to_addr, subject: draft.subject, body: draft.body });
                          await net.approveDraft(draft.id);
                          setDraft({ ...draft, status: "approved" });
                        }, "Approuvé.")}>
                        Approuver
                      </button>
                    )}
                    {draft.status === "approved" && (
                      <button className="btn btn-copper" disabled={busy || !status.send}
                        onClick={() => run(async () => { await net.sendDraft(draft.id); setDraft({ ...draft, status: "sent" }); }, "E-mail envoyé.")}>
                        {status.send ? "Envoyer" : "Envoi NON DISPONIBLE (SMTP)"}
                      </button>
                    )}
                    <button className="btn btn-line" onClick={() => copy(draft.body, say)}>Copier</button>
                    {draft.status === "sent" && <span className="badge">Envoyé</span>}
                  </div>
                </div>
              )}
            </section>
          )}
        </div>
        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    </div>
  );
}

const KIND: Record<string, string> = { fact: "Fait", preference: "Préférence", correction: "Correction", task: "Tâche" };
const NATURE: Record<string, string> = { fact: "Fait", preference: "Préférence", inference: "À confirmer", temporary: "Temporaire" };

export function Memoire() {
  const [items, setItems] = useState<Memo[]>([]);
  const [pending, setPending] = useState<Memo[]>([]);
  const [conflicts, setConflicts] = useState<MemConflict[]>([]);
  const [state, setState] = useState<MemState | null>(null);
  const [text, setText] = useState("");
  const [kind, setKind] = useState("fact");
  const { msg, say } = useToast();
  const load = () => {
    net.memoriesBy("active").then((all) => {
      setPending(all.filter((m) => m.nature === "inference"));
      setItems(all.filter((m) => m.nature !== "inference"));
    }).catch((e) => say(e.message));
    net.memState().then(setState).catch(() => {});
    net.memConflicts().then(setConflicts).catch(() => {});
  };
  useEffect(() => {
    load();
  }, []);
  const decide = async (id: string, action: string) => {
    try {
      await net.decideMemory(id, action);
      load();
    } catch (e: any) {
      say(e.message);
    }
  };
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Mémoire</h1>
        <p className="lede">
          Ce que l'assistant sait de vous, dans toutes les conversations. Dites « Retiens que… » dans le chat, ou ajoutez ici.
          Ce qu'il devine reste à confirmer. Supprimez ce qui est faux.
        </p>
        {state?.avertissement && <div className="card-box warn" role="alert"><I.Alert size={16} /> {state.avertissement}</div>}
        {state && (
          <p className="hint">
            {state.actifs} actifs · {state.a_confirmer} à confirmer · {state.taches} tâches · {state.conflits} conflits ·
            recherche {state.recherche}
          </p>
        )}
        {conflicts.length > 0 && (
          <section className="card-box warn">
            <label>Souvenirs qui se contredisent ({state?.portee_conflits ?? "numériques"})</label>
            {conflicts.map((c, i) => (
              <div key={i} className="conflict">
                <p className="hint">{c.raison}</p>
                {[c.a, c.b].map((m) => (
                  <div className="toolbar" key={m.id}>
                    <span className="post-body">{m.text}</span>
                    <button className="btn btn-line btn-small" onClick={() => decide(m.id, "pin")}>Garder</button>
                    <button className="btn btn-ghost btn-small" onClick={() => decide(m.id, "archive")}>Archiver</button>
                  </div>
                ))}
              </div>
            ))}
          </section>
        )}
        {pending.length > 0 && (
          <section className="card-box">
            <label>À confirmer — l'IA a deviné, vous tranchez</label>
            {pending.map((m) => (
              <div className="toolbar" key={m.id}>
                <span className="post-body">{m.text}</span>
                <button className="btn btn-copper btn-small" aria-label="Confirmer" onClick={() => decide(m.id, "confirm")}><I.Check size={16} /></button>
                <button className="btn btn-ghost btn-small" aria-label="Rejeter" onClick={() => decide(m.id, "reject")}><I.Close size={16} /></button>
              </div>
            ))}
          </section>
        )}
        <section className="card-box">
          <label>Nouveau souvenir</label>
          <textarea rows={2} value={text} maxLength={500} onChange={(e) => setText(e.target.value)}
            placeholder="Ex. Je facture toujours un acompte de 30 % avant de commencer" />
          <div className="toolbar">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button className="btn btn-copper" disabled={text.trim().length < 5}
              onClick={async () => {
                try {
                  await net.addMemory({ text, kind, pinned: true });
                  setText("");
                  load();
                } catch (e: any) {
                  say(e.message);
                }
              }}>
              Retenir
            </button>
          </div>
          <div className="toolbar">
            <label className="btn btn-line btn-small">
              Importer ChatGPT / Claude
              <input type="file" hidden accept=".json,.zip,.txt,.md"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  try {
                    const r = await net.importMemory(f);
                    say(`${r.candidats} suppositions trouvées : à confirmer ci-dessus`);
                    load();
                  } catch (err: any) {
                    say(err.message);
                  }
                }} />
            </label>
          </div>
        </section>
        {items.length === 0 && pending.length === 0 && <div className="empty">Rien en mémoire pour l'instant.</div>}
        {items.map((m) => (
          <article key={m.id} className="card-box">
            <p className="post-body">{m.text}</p>
            <div className="toolbar">
              <span className="badge">{NATURE[m.nature ?? ""] ?? KIND[m.kind] ?? m.kind}</span>
              {(m.occurrences ?? 1) > 1 && <span className="hint">vu {m.occurrences} fois</span>}
              {m.expires_at && <span className="hint">expire le {new Date(m.expires_at).toLocaleDateString("fr-FR")}</span>}
              <span className="hint">{m.source === "auto" ? "appris seul" : "demandé par vous"}</span>
              <button className="btn btn-ghost btn-small" onClick={() => decide(m.id, "archive")}>Archiver</button>
              <button className="btn btn-ghost btn-small"
                onClick={async () => {
                  await net.deleteMemory(m.id);
                  load();
                }}>
                Oublier
              </button>
            </div>
          </article>
        ))}
        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    </div>
  );
}

export function Journal() {
  const [rows, setRows] = useState<JournalRow[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    net.journal().then(setRows).catch((e) => setErr(e.message));
  }, []);
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Journal</h1>
        <p className="lede">Tout ce que l'IA et vous avez fait : outils appelés, brouillons, validations. Rien n'est envoyé sans vous.</p>
        {err && <p className="error">{err}</p>}
        {!err && rows.length === 0 && <div className="empty">Rien d'enregistré pour l'instant.</div>}
        {rows.map((r) => (
          <article key={r.id} className="card-box">
            <div className="toolbar">
              <b>{r.label}</b>
              <span className="hint">{r.at ? new Date(r.at).toLocaleString("fr-FR") : ""}</span>
            </div>
            {(r.target.trim() || r.details) && <p className="hint">{[r.target.trim(), r.details].filter(Boolean).join(" · ")}</p>}
          </article>
        ))}
      </div>
    </div>
  );
}
