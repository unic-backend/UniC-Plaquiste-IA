import { useEffect, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import * as I from "./Icons";
import { api, downloadAuth, net, shareDocument, type HiggsfieldStatus, type Post, type VideoAIClip, type VideoPlan, type VideoScene, type VideoState } from "./api";
import { duration, frText, sceneSeconds, statNumber, THEMES, totalSeconds } from "./videoBoard";

type Say = (m: string) => void;

const SCENE_FR: Record<string, string> = { title: "Titre", text: "Texte", photo: "Photo", gallery: "Galerie", stats: "Chiffres", quote: "Citation", page: "Défilement du site", outro: "Fin", ai_clip: "Clip IA (payant)", ai_image: "Image IA (payante)",
  typewriter: "Texte tapé", kinetic: "Titre animé", checklist: "Liste cochée", neon: "Néon", slogan: "Slogan" };
const sceneLabel = (c: { type: string; seconds?: number; [k: string]: unknown }) => {
  const d = c.type === "title" || c.type === "slogan" ? [c.l1, c.l2].filter(Boolean).join(" ") : c.type === "text" || c.type === "checklist" ? String(c.heading || "")
    : ["typewriter", "kinetic", "neon"].includes(c.type) && Array.isArray(c.lines) ? (c.lines as unknown[]).map(String).join(" ") : c.type === "ai_clip" || c.type === "ai_image" ? String(c.prompt || "").slice(0, 60) : c.caption ? String(c.caption) : "";
  return `${SCENE_FR[c.type] || c.type}${d ? ` · ${d}` : ""}${c.seconds ? ` · ${c.seconds} s` : ""}`;
};

const IMG_BASE = "https://www.unicplaquiste.com/images/";
const txt = (s: VideoScene, k: string) => (typeof s[k] === "string" ? frText(s[k]) : "");
const items = (s: VideoScene, k: string) => (Array.isArray(s[k]) ? (s[k] as unknown[]) : []);

/** Vignette d'une scène : son image finale en petit, aux couleurs de l'ambiance (un aperçu fidèle au contenu, pas le rendu exact du moteur). */
function SceneFrame({ s }: { s: VideoScene }) {
  const t = s.type;
  if (t === "title") return <>{txt(s, "l1") && <b className="f-t1">{txt(s, "l1")}</b>}{txt(s, "l2") && <b className="f-t2">{txt(s, "l2")}</b>}{txt(s, "sub") && <small className="f-sub">{txt(s, "sub")}</small>}</>;
  if (t === "text") return <div className="f-text">{txt(s, "heading") && <b className="f-h">{txt(s, "heading")}</b>}<ul>{items(s, "bullets").slice(0, 4).map((b, i) => <li key={i}>{frText(b)}</li>)}</ul></div>;
  if (t === "photo" || t === "gallery") {
    const imgs = t === "photo" ? [String(s.image || "")] : items(s, "images").map(String);
    const cap = [txt(s, "caption"), imgs.length > 1 ? `${imgs.length} photos` : ""].filter(Boolean).join(" · ");
    return <>{imgs[0] && <img className="f-img" src={IMG_BASE + imgs[0]} alt="" loading="lazy" referrerPolicy="no-referrer" onError={(e) => { e.currentTarget.style.display = "none"; }} />}{cap && <span className="f-cap">{cap}</span>}</>;
  }
  if (t === "stats") {
    const all = items(s, "items").slice(0, 4).map((it) => (it || {}) as { value?: unknown; suffix?: string; label?: string });
    const shownValues = all.map((o) => statNumber(o.value) + (o.suffix || ""));
    const fs = { "--fs": `${Math.min(12, 60 / Math.max(4, ...shownValues.map((v) => v.length)))}cqw` } as CSSProperties;   // même taille pour tous, le plus long tient (comme le moteur)
    return <div className="f-stats" style={fs}>{all.map((o, i) => <span key={i}><b>{shownValues[i]}</b><small>{frText(o.label)}</small></span>)}</div>;
  }
  if (t === "quote") return <><b className="f-q" aria-hidden>“</b><span className="f-qt">{txt(s, "text")}</span>{txt(s, "author") && <small className="f-sub">— {txt(s, "author")}</small>}</>;
  if (t === "outro") {
    const L = items(s, "lines").map(frText).filter(Boolean);
    return <>{L[0] && <b className="f-t1">{L[0]}</b>}{L.slice(1, 4).map((l, i) => <small key={i} className={i === 2 ? "f-btn" : "f-sub"}>{l}</small>)}</>;
  }
  if (t === "page") return <><b className="f-h">Le site défile</b>{items(s, "chapters").slice(0, 6).map((c, i) => <small key={i} className="f-chip">{frText((c as { label?: string })?.label)}</small>)}</>;
  if (t === "ai_clip" || t === "ai_image") return <div className="f-ai"><b>{t === "ai_clip" ? "Clip IA" : "Image IA"}</b><small>{txt(s, "prompt")}</small></div>;
  const bg = typeof s.image === "string" && s.image ? <img className="f-img" src={IMG_BASE + s.image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={(e) => { e.currentTarget.style.display = "none"; }} /> : null;
  const L = items(s, "lines").map(frText).filter(Boolean);
  if (t === "typewriter") return <>{bg}{L.map((l, i) => <small key={i} className="f-sub">{l}{i === L.length - 1 ? " ▍" : ""}</small>)}</>;
  if (t === "kinetic" || t === "neon") {   // le dernier mot en couleur d'accent, comme dans la vidéo
    const words = L.join(" ").split(" "), last = words.pop() || "";
    return <>{bg}{txt(s, "tag") && <small className="f-chip">{txt(s, "tag")}{txt(s, "place") ? ` · ${txt(s, "place")}` : ""}</small>}<b className="f-t2">{words.join(" ")} <span style={{ color: "var(--vac)" }}>{last}</span></b></>;
  }
  if (t === "checklist") return <>{bg}<div className="f-text">{txt(s, "heading") && <b className="f-h">{txt(s, "heading")}</b>}<ul>{items(s, "items").slice(0, 5).map((b, i) => <li key={i}>✓ {frText(b)}</li>)}</ul></div></>;
  if (t === "slogan") return <>{txt(s, "l1") && <b className="f-t2">{txt(s, "l1")}</b>}{txt(s, "l2") && <b className="f-t1">{txt(s, "l2")}</b>}{L.slice(0, 2).map((l, i) => <small key={i} className="f-sub">{l}</small>)}</>;
  return <small>{t}</small>;
}

/** Le scénario en vignettes, dans l'ordre : le patron voit ce que l'IA a compris avant de lancer ; une scène se retire d'un geste. */
function Storyboard({ spec, onRemove, busy }: { spec: VideoPlan["spec"]; onRemove: (i: number) => void; busy: boolean }) {
  const th = THEMES[spec.theme || "unic"] || THEMES.unic;
  const vars = { "--vbg": th.bg, "--vfg": th.fg, "--vac": th.accent, "--vsoft": th.soft, "--vg1": th.g1, "--vg2": th.g2, "--vcbg": th.cardBg, "--vcfg": th.cardFg } as CSSProperties;
  const n = spec.scenes.length;
  return (
    <ol className="vs-board" data-fmt={spec.format} style={vars} aria-label={`Aperçu du scénario : ${n} scènes, ambiance ${th.name}`}>
      {spec.scenes.map((s, i) => (
        <li key={`${i}:${sceneLabel(s)}`}>
          <div className={`vs-frame is-${s.type}`} role="img" aria-label={`Scène ${i + 1} : ${sceneLabel(s)}`}>
            <SceneFrame s={s} />
            <span className="vs-n" aria-hidden>{i + 1}</span>
          </div>
          <span className="vs-cap">{SCENE_FR[s.type] || s.type} · {duration(sceneSeconds(s))}</span>
          {n > 1 && <button type="button" className="vs-x" disabled={busy} aria-label={`Retirer la scène ${i + 1}`} title="Retirer cette scène" onClick={() => onRemove(i)}>×</button>}
        </li>
      ))}
    </ol>
  );
}

/** Studio vidéo : montage déterministe long via GitHub et clips courts générés par Higgsfield, sans publication automatique. */
export function VideoStudio({ say }: { say: Say }) {
  const [brief, setBrief] = useState("");
  const [fmt, setFmt] = useState("vertical");
  const [plan, setPlan] = useState<VideoPlan | null>(null);
  const [theme, setTheme] = useState("auto");
  const [changes, setChanges] = useState<string[]>([]);   // corrections déjà appliquées au scénario affiché
  const [fix, setFix] = useState("");
  const [planning, setPlanning] = useState(false);
  const [vid, setVid] = useState<VideoState | null>(null);
  const [got, setGot] = useState<{ url: string; filename: string } | null>(null);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiDuration, setAiDuration] = useState(5);
  const [aiAudio, setAiAudio] = useState(true);
  const [longPromptsText, setLongPromptsText] = useState("");
  const [longDuration, setLongDuration] = useState(60);
  const [aiClip, setAiClip] = useState<VideoAIClip | null>(null);
  const [hf, setHf] = useState<HiggsfieldStatus | null>(null);
  const [mode, setMode] = useState<"montage" | "clip" | "long">("montage");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  useEffect(() => {
    let alive = true;
    api.higgsfield().then((s) => { if (alive) setHf(s); }).catch(() => {});
    net.videoAiStatus().then((s) => { if (alive && s.state !== "idle") setAiClip(s); }).catch(() => {});
    net.videoDraft().then((d) => {   // scénario préparé dans le chat (outil plan_video) : ouvert une fois, prêt à relire et lancer
      if (!alive || !d.plan || !d.at) return;
      try { if (localStorage.getItem("unic.video.draft") === d.at) return; localStorage.setItem("unic.video.draft", d.at); } catch { /* ignoré */ }
      setMode("montage"); setBrief(d.brief || ""); setPlan(d.plan); setChanges(d.plan.changes ?? []);
      if (d.plan.spec?.format) setFmt(d.plan.spec.format);
      say("Scénario préparé dans le chat : relis-le, corrige si besoin, puis « Lancer la fabrication ».");
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const vidState = vid?.state;
  useEffect(() => {   // le montage (et la génération IA qui le précède) se suit tout seul : plus besoin d'appuyer sur « Où en est la vidéo ? »
    if (vidState !== "building") return;
    let cancelled = false;
    const timer = setInterval(() => { net.videoStatus().then((s) => { if (!cancelled) setVid(s); }).catch(() => {}); }, 10000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [vidState]);
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
  const running = !!aiClip && ["submitting", "queued", "processing", "assembling"].includes(aiClip.state);
  // le scénario tel qu'il partira : format et ambiance choisis maintenant (un changement de puce s'applique sans réécrire le scénario)
  const shown = plan ? { ...plan.spec, format: fmt, theme: theme === "auto" ? plan.spec.theme || "unic" : theme } : null;
  const propose = (correction?: string) => run(async () => {
    setPlanning(true);
    try {
      const next = correction ? [...changes, correction].slice(-12) : [];   // le fil des corrections : les 12 dernières
      const p = await net.videoPlan(brief, fmt, theme, correction && shown ? shown : undefined, next);
      setPlan(p); setChanges(p.changes ?? next); setFix("");
      if (p.spec.format !== fmt) setFmt(p.spec.format);   // la demande réclamait un autre format : la puce suit (la note le dit)
    } finally { setPlanning(false); }
  });
  const removeScene = (i: number) => setPlan((p) => {
    if (!p) return p;
    const scenes = p.spec.scenes.filter((_, j) => j !== i);
    return { ...p, spec: { ...p.spec, scenes }, seconds: totalSeconds(scenes), note: "Scène retirée : la durée est recalculée. « Corriger » pour aller plus loin." };
  });
  const longLines = longPromptsText.split("\n").map((l) => l.trim()).filter(Boolean);
  const clipsNeeded = longDuration / 30;
  const fmtName = fmt === "vertical" ? "vertical 9:16" : fmt === "horizontal" ? "horizontal 16:9" : "carré 1:1";
  return (
    <section className="card-box vs">
      <label>Studio vidéo</label>
      <p className="hint">Décris n'importe quelle vidéo : histoire, tutoriel, annonce, promo, récit, animaux, voyage… Rien n'est publié : la vidéo arrive dans tes documents.</p>

      <div className="seg" role="tablist" aria-label="Type de vidéo">
        {([["montage", "Montage", "gratuit"], ["clip", "Clip IA", "payant"], ["long", "Vidéo IA longue", "payant"]] as const).map(([k, name, tag]) => (
          <button key={k} role="tab" aria-selected={mode === k} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>
            <span>{name}<small className="vs-tag"> {tag}</small></span>
          </button>
        ))}
      </div>

      <div className="vs-fmt" role="radiogroup" aria-label="Format de la vidéo">
        {([["vertical", "Vertical 9:16"], ["horizontal", "Horizontal 16:9"], ["square", "Carré 1:1"]] as const).map(([k, name]) => (
          <button key={k} role="radio" aria-checked={fmt === k} className={`chip${fmt === k ? " on" : ""}`} onClick={() => setFmt(k)}>{name}</button>
        ))}
      </div>
      <p className="vs-note">Vertical : WhatsApp, TikTok, Reels · Horizontal : YouTube, écran · Carré : Facebook, Instagram.</p>

      {mode === "montage" && (
        <>
          <textarea rows={4} value={brief} onChange={(e) => setBrief(e.target.value)} maxLength={20000} placeholder="Ex. Une vidéo de 40 secondes qui raconte l’histoire de Dakar, avec des chiffres clés et une citation" aria-label="Description de la vidéo" />
          <p className="vs-note">Montage gratuit : titres, textes, chiffres, citations, photos du site et ambiances de couleurs (l'IA choisit celle du sujet). Il ne crée pas d'images ni de films : pour un lion qui court, utilise « Clip IA ». Pas de limite de durée : une longue vidéo est coupée en tronçons rendus en parallèle. {brief.length.toLocaleString("fr-FR")} / 20 000 caractères.</p>
          <div className="vs-fmt" role="radiogroup" aria-label="Ambiance de la vidéo">
            {["auto", ...Object.keys(THEMES)].map((k) => (
              <button key={k} role="radio" aria-checked={theme === k} className={`chip${theme === k ? " on" : ""}`} onClick={() => setTheme(k)}>
                {k !== "auto" && <i className="vs-dot" style={{ background: THEMES[k].bg, boxShadow: `inset 0 0 0 3px ${THEMES[k].accent}` }} aria-hidden />}
                {k === "auto" ? "Ambiance auto" : THEMES[k].name}
              </button>
            ))}
          </div>
          <div className="row-actions">
            <button className="btn btn-copper btn-small" disabled={busy} onClick={() => propose()}>{plan ? "Nouveau scénario" : "Proposer un scénario"}</button>
            <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setVid(await net.videoStatus()); })}>Où en est la vidéo ?</button>
          </div>
          {planning && <p className="vs-status" role="status">UniC lit ta demande et écrit le scénario… Souvent moins d'une minute ; plus pour une longue vidéo.</p>}
          {plan && shown && (
            <div className="vs-plan">
              {plan.understood && <div className="vs-understood"><b>Ce que j'ai compris</b>{plan.understood}</div>}
              {!!plan.assumptions?.length && (<><p className="vs-h">J'ai supposé — corrige-moi si c'est faux</p><ul className="vs-list">{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></>)}
              {!!plan.limits?.length && (<><p className="vs-h">Ce que le montage ne sait pas faire</p><ul className="vs-list">{plan.limits.map((a, i) => <li key={i}>{a}</li>)}</ul></>)}
              <p className="vs-sum"><b>{shown.scenes.length} scènes</b> · environ {duration(plan.seconds)}</p>
              <p className="vs-note">{plan.note}</p>
              {plan.ai && plan.ai.clips + plan.ai.images > 0 && (
                <p className="vs-status">⚠️ {plan.ai.clips} clip(s) et {plan.ai.images} image(s) générés par l'IA : <b>crédits Higgsfield payants</b>, un média à la fois. Les films IA sont muets dans le montage. Tu peux fermer l'application pendant la génération.</p>
              )}
              <Storyboard spec={shown} onRemove={removeScene} busy={busy} />
              <p className="vs-h">Corriger le scénario</p>
              <textarea className="vs-fix" rows={3} value={fix} onChange={(e) => setFix(e.target.value)} maxLength={2000} aria-label="Corriger le scénario"
                placeholder="Ex. plus court, change la scène 3, ajoute une citation…" />
              <div className="row-actions">
                <button className="btn btn-line btn-small" disabled={busy || !fix.trim()} onClick={() => propose(fix.trim())}>Corriger</button>
              </div>
              {changes.length > 0 && <p className="vs-note">Corrections appliquées : {changes.map((c, i) => `${i + 1}. ${c}`).join(" · ")}</p>}
              <button className="btn btn-copper" disabled={busy}
                onClick={() => {
                  const paid = plan.ai ? plan.ai.clips + plan.ai.images : 0;
                  const msg = paid > 0
                    ? `Lancer la fabrication ? Elle génère ${plan.ai!.clips} clip(s) et ${plan.ai!.images} image(s) avec Higgsfield : ${paid} génération(s) payante(s) (crédits). Le montage part ensuite tout seul.`
                    : "Lancer la fabrication de la vidéo ? Le temps dépend de sa durée ; une vidéo longue peut prendre beaucoup plus longtemps.";
                  if (window.confirm(msg)) run(async () => { const r = await net.videoStart(shown); setPlan(null); setChanges([]); setVid({ state: "building", detail: r.note }); }, "Fabrication lancée.");
                }}>{plan.ai && plan.ai.clips + plan.ai.images > 0 ? "Lancer (génération IA payante)" : "Lancer la fabrication"}</button>
            </div>
          )}
          {vid && <p className="vs-status" role="status">{vid.detail} {vid.url && <a href={vid.url} target="_blank" rel="noopener noreferrer">Détail</a>}</p>}
          {vid?.state === "failed" && vid.can_retry && (
            <button className="btn btn-copper" disabled={busy} onClick={() => run(async () => { const r = await net.videoRetry(); setVid({ state: r.ok ? "building" : "failed", detail: r.note }); }, "Montage relancé (aucun nouveau crédit).")}>Relancer le montage (sans nouveau crédit)</button>
          )}
          {vid?.state === "ready" && !got && (
            <button className="btn btn-copper" disabled={busy} onClick={() => run(async () => { const r = await net.videoFetch(); setGot({ url: r.url, filename: r.filename }); }, "Vidéo rangée dans tes documents.")}>Récupérer la vidéo</button>
          )}
          {got && (
            <div className="row-actions">
              <button className="btn btn-copper btn-small" onClick={() => downloadAuth(got.url, got.filename).catch(() => {})}>Télécharger</button>
              <button className="btn btn-line btn-small" onClick={() => shareDocument(got.url, got.filename).catch((e) => say(e.message))}>Partager</button>
            </div>
          )}
        </>
      )}

      {mode !== "montage" && (
        <p className="vs-note">{hf?.connected
          ? `Higgsfield · Wan 3.0 Prime · 720p. Clips IA restants aujourd'hui : ${hf.video_left_today}/${hf.video_per_day}. Chaque clip consomme des crédits payants ; rien n'est lancé sans ta confirmation.`
          : "Higgsfield n'est pas connecté : colle tes clés dans Plus › Higgsfield pour activer ces deux modes."}</p>
      )}

      {mode === "clip" && (
        <>
          <textarea rows={4} value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} maxLength={1500}
            placeholder="Ex. Travelling cinématographique dans un salon moderne avec faux plafond BA13 et éclairage indirect chaleureux."
            aria-label="Consigne du clip vidéo IA" />
          <div className="vs-row">
            <label className="vs-field">Durée
              <select value={aiDuration} onChange={(e) => setAiDuration(Number(e.target.value))} aria-label="Durée du clip IA">
                <option value={5}>5 secondes</option><option value={10}>10 secondes</option><option value={15}>15 secondes</option><option value={30}>30 secondes</option>
              </select>
            </label>
            <label className="vs-check"><input type="checkbox" checked={aiAudio} onChange={(e) => setAiAudio(e.target.checked)} /> <span>Son généré par l'IA</span></label>
          </div>
          <button className="btn btn-copper" disabled={busy || running || !hf || !hf.connected || hf.video_left_today <= 0 || aiPrompt.trim().length < 8}
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
            }}>{running ? "Génération en cours…" : "Générer un clip IA"}</button>
        </>
      )}

      {mode === "long" && (
        <>
          <label className="vs-field">Durée finale
            <select value={longDuration} onChange={(e) => setLongDuration(Number(e.target.value))} aria-label="Durée de la vidéo IA longue">
              <option value={30}>30 secondes · 1 clip</option><option value={60}>1 minute · 2 clips</option><option value={120}>2 minutes · 4 clips</option>
              <option value={300}>5 minutes · 10 clips</option><option value={600}>10 minutes · 20 clips</option>
            </select>
          </label>
          <textarea rows={7} value={longPromptsText} onChange={(e) => setLongPromptsText(e.target.value)} maxLength={30000}
            placeholder={"Une consigne par ligne, une scène de 30 secondes chacune. Exemple :\nPlan cinématographique d’un salon contemporain avec faux plafond BA13...\nGros plan sur l’éclairage indirect et les finitions..."}
            aria-label="Consignes des scènes de la vidéo IA longue" />
          <p className={`vs-note${longLines.length === clipsNeeded ? " ok" : ""}`}>{longLines.length} / {clipsNeeded} consignes · {clipsNeeded} clips payants. Le son suit le réglage du mode « Clip IA ».</p>
          <button className="btn btn-copper" disabled={busy || !hf?.connected || hf.video_left_today < clipsNeeded || longLines.length !== clipsNeeded ||
            longPromptsText.split("\n").some((l) => l.trim().length > 0 && l.trim().length < 8) || running}
            onClick={() => {
              if (!window.confirm(`Créer une vidéo IA de ${longDuration / 60} minute(s) avec ${longLines.length} clips Higgsfield ? Chaque clip consomme des crédits payants, soit jusqu’à ${longLines.length} générations. Le traitement peut prendre longtemps. Continuer ?`)) return;
              run(async () => { const result = await net.videoAiLongStart(longLines, longDuration, fmt, aiAudio); setAiClip(result); api.higgsfield().then(setHf).catch(() => {}); },
                "Génération de la vidéo IA longue lancée.");
            }}>Générer la vidéo IA longue</button>
        </>
      )}

      {mode !== "montage" && aiClip && aiClip.state !== "idle" && (
        <p className="vs-status" role="status">
          {aiClip.kind === "long" && running ? `Progression : ${aiClip.completed_clips || 0}/${aiClip.total_clips || 0} clips terminés. ` : ""}{aiClip.detail}
        </p>
      )}
      {mode !== "montage" && aiClip?.state === "ready" && aiClip.artifact && (
        <div className="row-actions">
          <button className="btn btn-copper btn-small" onClick={() => downloadAuth(aiClip.artifact!.url, aiClip.artifact!.filename).catch(() => {})}>{aiClip.kind === "long" ? "Télécharger la vidéo IA longue" : "Télécharger le clip IA"}</button>
          <button className="btn btn-line btn-small" onClick={() => shareDocument(aiClip.artifact!.url, aiClip.artifact!.filename).catch((e) => say(e.message))}>Partager</button>
        </div>
      )}
      <p className="vs-note">Si un moteur ne sait pas réaliser une demande, UniC te le signale au lieu d'en changer à ta place.</p>
    </section>
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
