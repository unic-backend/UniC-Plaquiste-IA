import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as I from "./Icons";
import { api, downloadAuth, net, shareDocument, type HiggsfieldStatus, type Post, type VideoAIClip, type VideoPlan } from "./api";

type Say = (m: string) => void;

const SCENE_FR: Record<string, string> = { title: "Titre", text: "Texte", photo: "Photo", gallery: "Galerie", stats: "Chiffres", quote: "Avis client", page: "Défilement du site", outro: "Fin (contact)" };
const sceneLabel = (c: { type: string; seconds?: number; [k: string]: unknown }) => {
  const d = c.type === "title" ? [c.l1, c.l2].filter(Boolean).join(" ") : c.type === "text" ? String(c.heading || "") : c.caption ? String(c.caption) : "";
  return `${SCENE_FR[c.type] || c.type}${d ? ` · ${d}` : ""}${c.seconds ? ` · ${c.seconds} s` : ""}`;
};

/** Studio vidéo : montage déterministe long via GitHub et clips courts générés par Higgsfield, sans publication automatique. */
export function VideoStudio({ say }: { say: Say }) {
  const [brief, setBrief] = useState("");
  const [fmt, setFmt] = useState("vertical");
  const [plan, setPlan] = useState<VideoPlan | null>(null);
  const [vid, setVid] = useState<{ state: string; detail: string; url?: string } | null>(null);
  const [got, setGot] = useState<{ url: string; filename: string } | null>(null);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiDuration, setAiDuration] = useState(5);
  const [aiAudio, setAiAudio] = useState(true);
  const [longPromptsText, setLongPromptsText] = useState("");
  const [longDuration, setLongDuration] = useState(60);
  const [aiClip, setAiClip] = useState<VideoAIClip | null>(null);
  const [hf, setHf] = useState<HiggsfieldStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  useEffect(() => {
    let alive = true;
    api.higgsfield().then((s) => { if (alive) setHf(s); }).catch(() => {});
    net.videoAiStatus().then((s) => { if (alive && s.state !== "idle") setAiClip(s); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const aiState = aiClip?.state;
  useEffect(() => {
    if (!aiState || !["submitting", "queued", "processing", "assembling"].includes(aiState)) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await net.videoAiStatus();
        if (cancelled) return;
        setAiClip(next);
        if (["submitting", "queued", "processing", "assembling"].includes(next.state)) timer = setTimeout(poll, 5000);
        else api.higgsfield().then((s) => { if (!cancelled) setHf(s); }).catch(() => {});
      } catch {
        if (!cancelled) timer = setTimeout(poll, 10000);
      }
    };
    timer = setTimeout(poll, 5000);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [aiState]);
  return (
    <>
    <section className="card-box">
        <label>Studio vidéo</label>
        <p className="hint">Décris la vidéo voulue (promo d'un service, présentation, avant/après, témoignage, annonce…). **Mode gratuit prioritaire** : le scénario et le montage Chrome + FFmpeg tournent via GitHub Actions, sans crédits vidéo payants. L’IA écrit le scénario avec tes photos et tes vrais chiffres ; jusqu’à 10 minutes. Vertical : WhatsApp, TikTok, Reels. Horizontal : YouTube, écran. Carré : Facebook, Instagram. Le temps de fabrication dépend de la durée. Rien n’est publié : la vidéo arrive dans tes documents.</p>
        <textarea rows={3} value={brief} onChange={(e) => setBrief(e.target.value)} maxLength={20000} placeholder="Ex. Vidéo de 30 secondes sur les faux plafonds BA13, avec nos réalisations" aria-label="Description de la vidéo" />
        <p className="hint">{brief.length.toLocaleString("fr-FR")} / 20 000 caractères · jusqu’à 200 scènes · 600 secondes maximum (10 minutes).</p>
        <select value={fmt} onChange={(e) => setFmt(e.target.value)} aria-label="Format de la vidéo">
          <option value="vertical">Vertical 9:16</option>
          <option value="horizontal">Horizontal 16:9</option>
          <option value="square">Carré 1:1</option>
        </select>
        <div className="row-actions">
          <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setPlan(await net.videoPlan(brief, fmt)); })}>Proposer un scénario</button>
          <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setVid(await net.videoStatus()); })}>Où en est la vidéo ?</button>
        </div>
        {plan && (
          <>
            <p className="hint">{plan.note} Scènes : {plan.spec.scenes.length}/200. Durée : environ {plan.seconds} s (maximum 600 s / 10 min). {plan.route?.reason || ""}</p>
            <ol className="hint">{plan.spec.scenes.map((c, i) => <li key={i}>{sceneLabel(c)}</li>)}</ol>
            <button className="btn btn-copper btn-small" disabled={busy}
              onClick={() => { if (window.confirm("Lancer la fabrication de la vidéo ? Le temps dépend de sa durée ; une vidéo longue peut prendre beaucoup plus longtemps.")) run(async () => { const r = await net.videoStart(plan.spec); setPlan(null); setVid({ state: "building", detail: r.note }); }, "Fabrication lancée."); }}>Lancer la fabrication</button>
          </>
        )}
        {vid && <p className="hint">{vid.detail} {vid.url && <a href={vid.url} target="_blank" rel="noopener noreferrer">Détail</a>}</p>}
        {vid?.state === "ready" && !got && (
          <button className="btn btn-copper btn-small" disabled={busy} onClick={() => run(async () => { const r = await net.videoFetch(); setGot({ url: r.url, filename: r.filename }); }, "Vidéo rangée dans tes documents.")}>Récupérer la vidéo</button>
        )}
        {got && (
          <div className="row-actions">
            <button className="btn btn-copper btn-small" onClick={() => downloadAuth(got.url, got.filename).catch(() => {})}>Télécharger</button>
            <button className="btn btn-line btn-small" onClick={() => shareDocument(got.url, got.filename).catch((e) => say(e.message))}>Partager</button>
          </div>
        )}
    </section>
    <section className="card-box">
      <label>Vidéo générative avancée (option payante)</label>
      <p className="hint">Utilise ce mode seulement si tu as besoin de vrais humains photoréalistes, de mouvements complexes ou d’une scène que le montage gratuit ne peut pas produire. Higgsfield · Wan 3.0 Prime · 720p · clips de 2 à 30 secondes. Chaque génération consomme des crédits payants ; le mode gratuit reste prioritaire et rien n'est lancé sans confirmation.</p>
      {hf?.connected ? (
        <p className="hint">Clips IA restants aujourd'hui : {hf.video_left_today}/{hf.video_per_day}. Format : {fmt === "vertical" ? "vertical 9:16" : fmt === "horizontal" ? "horizontal 16:9" : "carré 1:1"}.</p>
      ) : (
        <p className="hint">Higgsfield n'est pas connecté. Configure les clés dans Plus › Higgsfield pour activer la génération.</p>
      )}
      <textarea rows={3} value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} maxLength={1500}
        placeholder="Ex. Travelling cinématographique dans un salon moderne avec faux plafond BA13 et éclairage indirect chaleureux."
        aria-label="Consigne du clip vidéo IA" />
      <div className="row-actions">
        <label className="hint">Durée
          <select value={aiDuration} onChange={(e) => setAiDuration(Number(e.target.value))} aria-label="Durée du clip IA">
            <option value={5}>5 secondes</option>
            <option value={10}>10 secondes</option>
            <option value={15}>15 secondes</option>
            <option value={30}>30 secondes</option>
          </select>
        </label>
        <label className="hint"><input type="checkbox" checked={aiAudio} onChange={(e) => setAiAudio(e.target.checked)} /> Générer le son IA</label>
      </div>
      <button className="btn btn-copper btn-small" disabled={busy || !hf || !hf.connected || hf.video_left_today <= 0 || aiPrompt.trim().length < 8}
        onClick={() => {
          if (!window.confirm(`Générer un clip de ${aiDuration} secondes avec Higgsfield ? Cette action consomme des crédits payants (coût variable selon la durée et ton compte). Plafond : ${hf?.video_per_day ?? 20} clips par jour.`)) return;
          run(async () => {
            try {
              const result = await net.videoAiStart(aiPrompt, aiDuration, fmt, aiAudio);
              setAiClip(result);
            } finally {
              api.higgsfield().then(setHf).catch(() => {});
            }
          }, "Génération du clip IA lancée.");
        }}>{aiClip && ["submitting", "queued", "processing", "assembling"].includes(aiClip.state) ? "Génération en cours…" : "Générer un clip IA"}</button>
      {aiClip && aiClip.state !== "idle" && <p className="hint" role="status">{aiClip.detail}</p>}
      {aiClip?.state === "ready" && aiClip.artifact && (
        <div className="row-actions">
          <button className="btn btn-copper btn-small" onClick={() => downloadAuth(aiClip.artifact!.url, aiClip.artifact!.filename).catch(() => {})}>{aiClip.kind === "long" ? "Télécharger la vidéo IA longue" : "Télécharger le clip IA"}</button>
          <button className="btn btn-line btn-small" onClick={() => shareDocument(aiClip.artifact!.url, aiClip.artifact!.filename).catch((e) => say(e.message))}>Partager</button>
        </div>
      )}

      <hr />
      <label>Vidéo générative longue (option payante)</label>
      <p className="hint">À utiliser uniquement si tu veux plusieurs scènes réellement générées par un modèle vidéo. Pour les publicités, présentations, photos animées, textes, transitions et montages classiques, utilise le Studio vidéo gratuit au-dessus. Ici, chaque scène génère un clip Higgsfield payant de 30 secondes maximum ; jusqu’à 10 minutes et 20 clips. Le son IA est réglé ci-dessus.</p>
      <label className="hint">Durée finale
        <select value={longDuration} onChange={(e) => setLongDuration(Number(e.target.value))} aria-label="Durée de la vidéo IA longue">
          <option value={30}>30 secondes · 1 clip</option>
          <option value={60}>1 minute · 2 clips</option>
          <option value={120}>2 minutes · 4 clips</option>
          <option value={300}>5 minutes · 10 clips</option>
          <option value={600}>10 minutes · 20 clips</option>
        </select>
      </label>
      <textarea rows={8} value={longPromptsText} onChange={(e) => setLongPromptsText(e.target.value)} maxLength={30000}
        placeholder={"Une consigne par ligne, une scène de 30 secondes chacune. Exemple :\nPlan cinématographique d’un salon contemporain avec faux plafond BA13...\nGros plan sur l’éclairage indirect et les finitions..."}
        aria-label="Consignes des scènes de la vidéo IA longue" />
      <p className="hint">{longPromptsText.split("\n").filter((s) => s.trim()).length} / {longDuration / 30} consignes requises · {longDuration / 30} clips payants prévus.</p>
      <button className="btn btn-copper btn-small" disabled={busy || !hf?.connected || hf.video_left_today < longDuration/30 ||
        longPromptsText.split("\n").filter((s) => s.trim()).length !== longDuration/30 ||
        longPromptsText.split("\n").some((s) => s.trim().length > 0 && s.trim().length < 8) ||
        (aiClip !== null && ["submitting", "queued", "processing", "assembling"].includes(aiClip.state))}
        onClick={() => {
          const prompts = longPromptsText.split("\n").map((s) => s.trim()).filter(Boolean);
          if (!window.confirm(`Créer une vidéo IA de ${longDuration/60} minute(s) avec ${prompts.length} clips Higgsfield ? Chaque clip consomme des crédits payants, soit jusqu’à ${prompts.length} générations. Le traitement peut prendre longtemps. Continuer ?`)) return;
          run(async () => { const result = await net.videoAiLongStart(prompts, longDuration, fmt, aiAudio); setAiClip(result); api.higgsfield().then(setHf).catch(() => {}); },
            "Génération de la vidéo IA longue lancée.");
        }}>Générer la vidéo IA longue</button>
      {aiClip?.kind === "long" && ["submitting", "queued", "processing", "assembling"].includes(aiClip.state) &&
        <p className="hint" role="status">Progression : {aiClip.completed_clips || 0}/{aiClip.total_clips || 0} clips terminés. {aiClip.detail}</p>}

    </section>
    </>
  );
}

/** Connexion du site (GitHub → Netlify) et rédaction de pages par l'IA. */
export function SiteConnect({ say, onChange, onDraft }: { say: Say; onChange?: (connected: boolean) => void; onDraft: () => void }) {
  const [st, setSt] = useState<{ connected: boolean; repo: string; site_url: string } | null>(null);
  const [token, setToken] = useState("");
  const [topic, setTopic] = useState("");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [book, setBook] = useState<string | null>(null);
  const refresh = () => net.siteStatus().then((s) => { setSt(s); onChange?.(s.connected); }).catch((e) => say(e.message));
  useEffect(() => { refresh(); }, []);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  if (!st) return null;
  return (
    <>
      <section className="card-box">
        <label>Connexion du site</label>
        {st.connected ? (
          <>
            <p className="post-body"><I.Check size={16} /> {st.site_url.replace("https://", "")} relié au dépôt {st.repo}</p>
            <p className="hint">Une page n'est publiée que si tu l'approuves puis touches « Publier sur le site ». L'accueil n'est jamais modifié.</p>
            <button className="btn btn-ghost btn-small" disabled={busy}
              onClick={() => { if (window.confirm("Déconnecter le site ? Le jeton sera effacé du serveur.")) run(async () => { await net.siteDisconnect(); await refresh(); }, "Site déconnecté."); }}>Déconnecter</button>
          </>
        ) : (
          <>
            <p className="hint">Le site est publié par Netlify depuis GitHub. Il faut un jeton GitHub limité à ce seul dépôt.</p>
            <button className="btn btn-line btn-small" onClick={() => setOpen((o) => !o)}>{open ? "Masquer les étapes" : "Voir les étapes"}</button>
            {open && (
              <ol className="steps">
                <li>Ouvre <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">github.com → nouveau jeton</a> (connecte-toi avec le compte unic-backend).</li>
                <li>Nom : <b>UniC AI</b> · Expiration : 1 an.</li>
                <li><b>Repository access</b> → <b>Only select repositories</b> → <b>site-unic-plaquiste</b>.</li>
                <li><b>Permissions</b> → Repository → <b>Contents : Read and write</b>.</li>
                <li><b>Generate token</b>, copie-le et colle-le ci-dessous.</li>
              </ol>
            )}
            <input type="password" autoComplete="off" placeholder="Jeton GitHub (github_pat_…)" value={token} onChange={(e) => setToken(e.target.value)} aria-label="Jeton GitHub" />
            <button className="btn btn-copper" disabled={busy || token.trim().length < 20}
              onClick={() => run(async () => { await net.siteConnect(token); setToken(""); await refresh(); }, "Site connecté.")}>Connecter le site</button>
          </>
        )}
      </section>
      <section className="card-box">
        <label>Portfolio d'entreprise</label>
        <p className="hint">Le portfolio est en ligne : une bannière « Voir notre portfolio » sur l'accueil du site mène à la page animée, avec le PDF A4 à télécharger. Il se modifie dans le dépôt du site (pull request que tu fusionnes), pas depuis ici.</p>
        <div className="row-actions">
        <a className="btn btn-copper btn-small" href="https://www.unicplaquiste.com/portfolio/" target="_blank" rel="noopener noreferrer">Ouvrir le portfolio</a>
        <a className="btn btn-line btn-small" href="https://www.unicplaquiste.com/portfolio/Portfolio-UniC-Plaquiste.pdf" target="_blank" rel="noopener noreferrer">Télécharger le PDF</a>
        </div>
        <details className="old-book">
          <summary>Ancienne version (Book)</summary>
          <p className="hint">Première version de la page, publiable sur unicplaquiste.com/book/. Elle n'a ni les effets de défilement ni la bannière : à n'utiliser que si tu en as besoin.</p>
          <button className="btn btn-line btn-small" disabled={busy}
            onClick={() => run(async () => { setBook((await net.bookPreview()).html); })}>Aperçu</button>
          {st.connected
            ? <button className="btn btn-line btn-small" disabled={busy}
                onClick={() => { if (window.confirm("Publier l'ancien Book sur unicplaquiste.com/book/ ?")) run(async () => { const r = await net.bookPublish(); window.open(r.url, "_blank"); }, "Book publié. Netlify met le site à jour dans 1 minute."); }}>Publier l'ancien Book</button>
            : <span className="hint"> Connecte le site ci-dessus pour publier.</span>}
        </details>
      </section>
      <VideoStudio say={say} />
      <section className="card-box">
        <label>Rédiger une page pour le site</label>
        <p className="hint">Une page par service ou par quartier fait monter ton site sur Google. L'IA n'invente aucun fait : donne-lui les vrais détails.</p>
        <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Ex. Faux plafond BA13 aux Almadies" aria-label="Sujet de la page" />
        <textarea rows={3} value={details} onChange={(e) => setDetails(e.target.value)} placeholder="Faits vrais à utiliser (type de travaux, quartier, particularités…)" aria-label="Faits à utiliser" />
        <button className="btn btn-copper" disabled={busy || topic.trim().length < 5}
          onClick={() => run(async () => { await net.siteDraft(topic, details); setTopic(""); setDetails(""); onDraft(); }, "Page rédigée : relis-la dans la liste ci-dessous.")}>
          Rédiger avec l'IA
        </button>
      </section>
      {book !== null && createPortal(
        <div className="preview-back" role="dialog" aria-label="Aperçu de l'ancien Book">
          <div className="preview-head"><span /><b>Aperçu de l'ancien Book</b><button className="tool" onClick={() => setBook(null)} aria-label="Fermer"><I.Stop size={18} /></button></div>
          <iframe title="Aperçu de l'ancien Book" srcDoc={book} sandbox="" style={{ flex: 1, border: 0, background: "#fff", width: "100%" }} />
        </div>, document.body)}
    </>
  );
}

/** Aperçu de la page (même habillage que le site) et publication d'une page approuvée. */
export function SitePageActions({ post, connected, say, onDone }: { post: Post; connected: boolean; say: Say; onDone: () => void }) {
  const [html, setHtml] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<string | null>(null);
  const save = async () => {
    if (edit === null) return;
    setBusy(true);
    try { await net.editPost(post.id, edit); setEdit(null); say("Texte enregistré."); onDone(); } catch (e: any) { say(e.message || "Enregistrement impossible"); } finally { setBusy(false); }
  };
  const preview = async () => {
    setBusy(true);
    try { setHtml((await net.sitePreview(post.id)).html); } catch (e: any) { say(e.message || "Aperçu impossible"); } finally { setBusy(false); }
  };
  const publish = async () => {
    if (!window.confirm("Publier cette page sur unicplaquiste.com ?")) return;
    setBusy(true);
    try { const r = await net.sitePublish(post.id); say("Publiée. Netlify met le site à jour dans 1 minute."); onDone(); window.open(r.url, "_blank"); }
    catch (e: any) { say(e.message || "Publication impossible"); } finally { setBusy(false); }
  };
  return (
    <div className="li-publish">
      {edit !== null && (
        <>
          <textarea rows={14} style={{ width: "100%" }} value={edit} onChange={(e) => setEdit(e.target.value)} aria-label="Texte de la page" />
          <button className="btn btn-copper btn-small" disabled={busy} onClick={save}>Enregistrer le texte</button>
          <button className="btn btn-ghost btn-small" onClick={() => setEdit(null)}>Annuler</button>
        </>
      )}
      {edit === null && post.status !== "approved" && <button className="btn btn-line btn-small" onClick={() => setEdit(post.body)}>Modifier</button>}
      <button className="btn btn-line btn-small" disabled={busy} onClick={preview}>Aperçu</button>
      {post.status === "approved" && (connected
        ? <button className="btn btn-copper btn-small" disabled={busy} onClick={publish}>Publier sur le site</button>
        : <span className="hint">Connecte le site ci-dessus pour publier.</span>)}
      {html !== null && createPortal(
        <div className="preview-back" role="dialog" aria-label="Aperçu de la page">
          <div className="preview-head"><span /><b>Aperçu</b><button className="tool" onClick={() => setHtml(null)} aria-label="Fermer"><I.Stop size={18} /></button></div>
          <iframe title="Aperçu" srcDoc={html} sandbox="" style={{ flex: 1, border: 0, background: "#fff", width: "100%" }} />
        </div>, document.body)}
    </div>
  );
}
