import * as I from "./Icons";
import { LinkedInConnect, LinkedInPublish } from "./LinkedIn";
import { sharePhoto } from "./Google";
import { useEffect, useState } from "react";
import { net, type JournalRow, type Usage, type MemConflict, type MemState, type Memo, type GProfile, type GReview, type Mail, type MailDraft, type Platform, type Post } from "./api";

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
  const [li, setLi] = useState<{ connected: boolean; pageReady: boolean }>({ connected: false, pageReady: false });
  const { msg, say } = useToast();
  const refreshLi = () => net.linkedinStatus().then((s) => setLi({ connected: s.connected, pageReady: s.connected && s.page_scope && !!s.page_id })).catch(() => {});
  useEffect(() => { refreshLi(); }, []);

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
        {sel === "linkedin" && <LinkedInConnect say={say} onChange={refreshLi} />}

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
            {d.platform === "linkedin" && d.status === "approved" && (
              <LinkedInPublish post={d} connected={li.connected} pageReady={li.pageReady} say={say} onDone={load} />
            )}
            {d.external_url && <p className="hint"><a href={d.external_url} target="_blank" rel="noopener noreferrer">Voir la publication</a></p>}
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
              {d.platform === "linkedin" && d.status !== "published" && (
                <button className="btn btn-line btn-small" onClick={async () => { try { say(await sharePhoto(null, `${d.body}${d.hashtags ? `\n\n${d.hashtags}` : ""}`, "LinkedIn", "Publication LinkedIn")); } catch { say("Partage annulé."); } }}>
                  Partager
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

/** Lien Google qui demande de se connecter AU compte indiqué (utile quand le téléphone est connecté à un autre compte). */
const googleLink = (email: string, target: string) =>
  email.includes("@")
    ? `https://accounts.google.com/AccountChooser?Email=${encodeURIComponent(email.trim())}&continue=${encodeURIComponent(target)}`
    : target;

export function Courrier() {
  const [status, setStatus] = useState<{ read: boolean; send: boolean; ai: boolean; note: string } | null>(null);
  const [mails, setMails] = useState<Mail[]>([]);
  const [open, setOpen] = useState<Mail | null>(null);
  const [info, setInfo] = useState<{ priority?: string; action?: string }>({});
  const [draft, setDraft] = useState<MailDraft | null>(null);
  const [instr, setInstr] = useState("");
  const [busy, setBusy] = useState(false);
  const [acct, setAcct] = useState<{ connected: boolean; address: string; env_override: boolean } | null>(null);
  const [gAddr, setGAddr] = useState("");
  const [gPwd, setGPwd] = useState("");
  const { msg, say } = useToast();
  const refresh = () => {
    net.mailStatus().then(setStatus).catch((e) => say(e.message));
    net.mailAccount().then(setAcct).catch(() => {});
  };

  const load = () => net.mails().then(setMails).catch((e) => say(e.message));
  useEffect(() => {
    refresh();
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
        {acct && !acct.env_override && (
          acct.connected ? (
            <section className="card-box">
              <label>Gmail connecté</label>
              <p className="post-body"><I.Check size={16} /> {acct.address}</p>
              <p className="hint">Lecture seule. Chaque réponse reste un brouillon : rien ne part sans ton approbation.</p>
              <button className="btn btn-ghost btn-small" disabled={busy}
                onClick={() => { if (window.confirm("Déconnecter Gmail ? Le mot de passe d'application sera effacé du serveur.")) run(async () => { await net.disconnectGmail(); refresh(); setMails([]); }, "Gmail déconnecté."); }}>
                Déconnecter
              </button>
            </section>
          ) : (
            <section className="card-box">
              <label>Connecter Gmail</label>
              <p className="hint">Étape 1 : écris l'adresse du compte à connecter (ton Gmail d'entreprise).</p>
              <input type="email" inputMode="email" autoComplete="off" placeholder="ton.adresse@gmail.com" value={gAddr} onChange={(e) => setGAddr(e.target.value)} />
              <ol className="steps" start={2}>
                <li>Touche <a href={googleLink(gAddr, "https://myaccount.google.com/signinoptions/twosv")} target="_blank" rel="noopener noreferrer">activer la validation en 2 étapes</a>. Google te demandera de te connecter à CE compte (pas ton compte perso). Tes autres comptes ne sont pas touchés.</li>
                <li>Touche <a href={googleLink(gAddr, "https://myaccount.google.com/apppasswords")} target="_blank" rel="noopener noreferrer">créer le mot de passe d'application</a> (nom : UniC AI). Google affiche 16 lettres : copie-les.</li>
                <li>Reviens ici et colle-les.</li>
              </ol>
              <input type="password" autoComplete="off" placeholder="Mot de passe d'application (16 lettres)" value={gPwd} onChange={(e) => setGPwd(e.target.value)} />
              <button className="btn btn-copper" disabled={busy || !gAddr.includes("@") || gPwd.replace(/\s/g, "").length < 16}
                onClick={() => run(async () => { await net.connectGmail(gAddr, gPwd); setGPwd(""); refresh(); load(); }, "Gmail connecté.")}>
                Connecter Gmail
              </button>
              <p className="hint">Ce mot de passe ne donne accès qu'à ta messagerie, il est chiffré sur ton serveur et tu peux le révoquer chez Google à tout moment.</p>
            </section>
          )
        )}
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


const usd = (n: number) => `${n.toLocaleString("fr-FR", { minimumFractionDigits: n < 1 ? 3 : 2, maximumFractionDigits: n < 1 ? 3 : 2 })} $`;

export function Couts() {
  const [u, setU] = useState<Usage | null>(null);
  const [credit, setCredit] = useState("");
  const [err, setErr] = useState("");
  const { msg, say } = useToast();
  const load = () => net.usage().then(setU).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
  }, []);
  if (err) return <div className="page"><div className="page-inner"><p className="error">{err}</p></div></div>;
  if (!u) return <div className="page"><div className="page-inner"><p className="hint">Chargement…</p></div></div>;
  const max = Math.max(0.0001, ...u.jours.map((j) => j.cout_usd));
  const pct = u.credit_usd && u.reste_usd !== null ? Math.max(0, Math.min(100, (u.reste_usd / u.credit_usd) * 100)) : null;
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Coût de Claude</h1>
        <p className="lede">Ce que chaque réponse consomme, calculé sur les jetons réels. {u.avertissement}</p>
        <section className="card-box">
          <label>Crédit restant (estimé)</label>
          {u.reste_usd === null ? (
            <p className="hint">Indique le crédit que tu as rechargé pour voir ce qu'il reste.</p>
          ) : (
            <>
              <div className="big-number">{usd(Math.max(0, u.reste_usd))}</div>
              <div className="meter"><i style={{ width: `${pct}%` }} className={pct !== null && pct < 20 ? "low" : ""} /></div>
              <p className="hint">
                sur {usd(u.credit_usd ?? 0)} rechargés
                {u.messages_restants_estimes !== null && <> · environ {u.messages_restants_estimes.toLocaleString("fr-FR")} messages au rythme actuel</>}
              </p>
            </>
          )}
          <div className="toolbar">
            <input type="number" inputMode="decimal" min="0" step="0.5" placeholder="Crédit rechargé, en $ (ex. 15)" value={credit}
              onChange={(e) => setCredit(e.target.value)} />
            <button className="btn btn-copper" disabled={credit === "" || Number(credit) < 0}
              onClick={async () => {
                try {
                  setU(await net.setBudget(Number(credit)));
                  setCredit("");
                  say("Crédit enregistré : le compteur repart de zéro.");
                } catch (e: any) {
                  say(e.message);
                }
              }}>
              Enregistrer
            </button>
          </div>
        </section>
        <div className="stat-grid">
          <div className="stat"><span>Aujourd'hui</span><b>{usd(u.aujourdhui_usd)}</b><i>{u.messages_aujourdhui} msg</i></div>
          <div className="stat"><span>7 jours</span><b>{usd(u.semaine_usd)}</b></div>
          <div className="stat"><span>Ce mois</span><b>{usd(u.mois_usd)}</b><i>{u.messages_mois} msg</i></div>
          <div className="stat"><span>Par message</span><b>{usd(u.moyenne_par_message_usd)}</b><i>{u.messages_total} au total</i></div>
        </div>
        <section className="card-box">
          <label>14 derniers jours</label>
          <div className="bars" role="img" aria-label="Coût par jour">
            {u.jours.map((j) => (
              <div key={j.jour} className="bar" title={`${j.jour} : ${usd(j.cout_usd)}`}>
                <i style={{ height: `${Math.max(3, (j.cout_usd / max) * 100)}%` }} />
                <span>{j.jour.slice(8)}</span>
              </div>
            ))}
          </div>
        </section>
        {u.par_modele.length > 0 && (
          <section className="card-box">
            <label>Par modèle</label>
            {u.par_modele.map((m) => (
              <div className="toolbar" key={m.model}>
                <b>{m.model}</b><span className="hint">{m.messages} msg</span><span>{usd(m.cout_usd)}</span>
              </div>
            ))}
          </section>
        )}
        {u.tarif_inconnu && <p className="hint">Certains calculs utilisent un tarif supposé (modèle inconnu).</p>}
        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    </div>
  );
}
