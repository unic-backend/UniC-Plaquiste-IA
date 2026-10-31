import { useEffect, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import * as I from "./Icons";
import { downloadAuth, fetchBlobUrl, net, shareDocument, type Post, type VideoMedia, type VideoPlan, type VideoScene, type VideoState } from "./api";
import { duration, frText, sceneSeconds, statNumber, THEMES, totalSeconds } from "./videoBoard";

type Say = (m: string) => void;

const SCENE_FR: Record<string, string> = { title: "Titre", text: "Texte", photo: "Photo", gallery: "Galerie", stats: "Chiffres", quote: "Citation", page: "Défilement du site", outro: "Fin", ai_clip: "Clip IA (payant)", ai_image: "Image IA (payante)",
  typewriter: "Texte tapé", kinetic: "Titre animé", checklist: "Liste cochée", neon: "Néon", slogan: "Slogan", my_clip: "Ma vidéo", my_photo: "Ma photo",
  counter: "Compteur", flow: "Schéma", wave: "Onde sonore", chat: "Bulle « commente »", badge: "Badge", lottie: "Animation" };
const ANIM_FR: Record<string, string> = { check: "✓ Validé", spark: "✦ Éclat", arrow: "→ Flèche", pin: "📍 Lieu", pulse: "◉ Ondes" };
/** Un panneau animé en quelques mots (vignettes et liste des animations d'un film). */
const panelText = (p: { [k: string]: unknown }) => {
  const L = Array.isArray(p.lines) ? (p.lines as unknown[]).map(String) : [];
  if (p.type === "counter") return `${statNumber(p.value)}${p.suffix ? (/^[+×]/.test(String(p.suffix)) ? "" : " ") + String(p.suffix) : ""}${p.label ? ` ${String(p.label)}` : ""}`;
  if (p.type === "flow") return (Array.isArray(p.steps) ? (p.steps as unknown[]).map(String) : []).join(" → ");
  if (p.type === "lottie") return [p.anim ? ANIM_FR[String(p.anim)] || String(p.anim) : "Ton animation", ...L].join(" · ");
  if (p.type === "checklist") return [String(p.heading || ""), ...(Array.isArray(p.items) ? (p.items as unknown[]).map(String) : [])].filter(Boolean).join(" · ");
  return L.join(" · ");
};
/** Montage d'un plan de la vidéo du patron, en mots (vignette, liste des scènes). */
const GRADE_FR: Record<string, string> = { cinema: "Cinéma", warm: "Chaud", night: "Nuit", crisp: "Net", bw: "Noir et blanc" };
const GRADE_CSS: Record<string, string> = { cinema: "contrast(1.1) saturate(1.18)", warm: "sepia(.18) saturate(1.2)", night: "brightness(1.12) saturate(1.05) hue-rotate(-8deg)",
  crisp: "contrast(1.08) saturate(1.1)", bw: "grayscale(1) contrast(1.15)" };
const ZOOM_FR: Record<string, string> = { in: "Zoom avant", out: "Zoom arrière", punch: "Coup de zoom" };
const TRANS_FR: Record<string, string> = { cut: "Coupe franche", flash: "Flash", slide: "Glissé" };
const clipEdits = (c: { [k: string]: unknown }) => {
  const sp = Number(c.speed) || 1, out: string[] = [];
  const x = (n: number) => `×${String(n).replace(".", ",")}`;
  if (sp < 1) out.push(`Ralenti ${x(sp)}`); else if (sp > 1) out.push(`Accéléré ${x(sp)}`);
  if (c.sound === true) out.push("Son du film");
  if (typeof c.zoom === "string" && ZOOM_FR[c.zoom]) out.push(ZOOM_FR[c.zoom]);
  if (typeof c.grade === "string" && GRADE_FR[c.grade]) out.push(GRADE_FR[c.grade]);
  if (c.split_media) out.push("Avant | après");
  if (c.layout === "split") out.push("Écran divisé");
  if (Array.isArray(c.panels) && c.panels.length) out.push(`${c.panels.length} animation${c.panels.length > 1 ? "s" : ""}`);
  if (Number(c.freeze) > 0) out.push("Arrêt sur image");
  if (typeof c.transition === "string" && TRANS_FR[c.transition]) out.push(TRANS_FR[c.transition]);
  return out;
};
const sceneLabel = (c: { type: string; seconds?: number; [k: string]: unknown }) => {
  const d = c.type === "title" || c.type === "slogan" ? [c.l1, c.l2].filter(Boolean).join(" ") : c.type === "text" || c.type === "checklist" ? String(c.heading || "")
    : ["typewriter", "kinetic", "neon"].includes(c.type) && Array.isArray(c.lines) ? (c.lines as unknown[]).map(String).join(" ") : c.type === "ai_clip" || c.type === "ai_image" ? String(c.prompt || "").slice(0, 60) : c.caption ? String(c.caption) : "";
  const ed = c.type === "my_clip" ? clipEdits(c).join(", ") : "";
  return `${SCENE_FR[c.type] || c.type}${d ? ` · ${d}` : ""}${ed ? ` · ${ed}` : ""}${c.seconds ? ` · ${c.seconds} s` : ""}`;
};

const IMG_BASE = "https://www.unicplaquiste.com/images/";
const txt = (s: VideoScene, k: string) => (typeof s[k] === "string" ? frText(s[k]) : "");
const items = (s: VideoScene, k: string) => (Array.isArray(s[k]) ? (s[k] as unknown[]) : []);

/** Images des vidéos du patron, gardées le temps de la page : une vignette n'est téléchargée qu'une fois. */
const clipFrames = new Map<string, Promise<string>>();

/** Vraie image du passage choisi dans la vidéo du patron (servie avec le code d'accès) ; cadre « Ma vidéo » si elle ne vient pas. */
function ClipThumb({ id, start, half, grade }: { id: string; start: number; half?: "l" | "r" | "b"; grade?: string }) {
  const key = `${id}@${Math.round(start * 2) / 2}`;
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setSrc(null); setFailed(false);
    if (!/^[a-f0-9]{12}$/.test(id)) { setFailed(true); return; }
    if (!clipFrames.has(key)) clipFrames.set(key, fetchBlobUrl(`/api/website/video/media/${id}/frame?t=${encodeURIComponent(String(start))}`));
    clipFrames.get(key)!.then((u) => { if (live) setSrc(u); }).catch(() => { clipFrames.delete(key); if (live) setFailed(true); });
    return () => { live = false; };
  }, [key, id, start]);
  if (failed || !src) return failed ? <b className="f-clip-tag">Ma vidéo</b> : null;
  return <img className={`f-img${half ? ` f-half-${half}` : ""}`} src={src} alt="" style={grade && GRADE_CSS[grade] ? { filter: GRADE_CSS[grade] } : undefined} />;
}

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
  if (t === "my_clip") {   // vraie vidéo du patron : texte incrusté éventuel
    const ov = (s.overlay || {}) as { lines?: unknown[] };
    const words = (ov.lines || []).map((x) => frText(x)).filter(Boolean).join(" ");
    const grade = typeof s.grade === "string" ? s.grade : undefined, split = typeof s.split_media === "string" ? s.split_media : "";
    const eds = clipEdits(s), stack = s.layout === "split";
    const first = Array.isArray(s.panels) && s.panels.length ? (s.panels[0] as { [k: string]: unknown }) : null;
    return <>
      {stack && <span className="f-top">{first ? <><small className="f-chip">{SCENE_FR[String(first.type)] || String(first.type)}</small><b className="f-t2">{frText(panelText(first))}</b></> : null}</span>}
      <ClipThumb id={String(s.media || "")} start={Number(s.start) || 0} half={stack ? "b" : split ? "l" : undefined} grade={grade} />
      {split && <><ClipThumb id={split} start={Number(s.split_start) || 0} half="r" grade={grade} /><i className="f-split" aria-hidden /></>}
      {!!eds.length && <small className="f-chip f-edits">{eds.join(" · ")}</small>}
      {words && <span className="f-cap">{words}</span>}
    </>;
  }
  if (t === "counter" || t === "flow" || t === "wave" || t === "chat" || t === "badge" || t === "lottie") {
    return <>{t === "counter" ? <b className="f-t1">{statNumber(s.value)}{s.suffix ? (/^[+×]/.test(String(s.suffix)) ? "" : " ") + String(s.suffix) : ""}</b> : <small className="f-chip">{SCENE_FR[t]}</small>}
      <b className="f-t2">{frText(t === "counter" ? String(s.label || "") : panelText(s))}</b></>;
  }
  if (t === "my_photo") return <><ClipThumb id={String(s.media || "")} start={0} />{txt(s, "caption") && <span className="f-cap">{txt(s, "caption")}</span>}</>;
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

const MEDIA_FR: Record<VideoMedia["kind"], string> = { clip: "Vidéo", photo: "Photo", music: "Musique", voice: "Voix off", lottie: "Animation" };
const MEDIA_ICON: Record<VideoMedia["kind"], string> = { clip: "🎬", photo: "📷", music: "🎵", voice: "🎙️", lottie: "✨" };
const ACCEPT_ALL = "video/*,image/jpeg,image/png,image/webp,audio/*,application/json,.mp4,.mov,.m4v,.webm,.jpg,.jpeg,.png,.webp,.mp3,.m4a,.aac,.wav,.ogg,.json";

/** Un média du patron en vignette : vraie image (vidéo, photo) ou icône (son, animation), ce que l'IA en sait, et les gestes utiles. */
function MediaTile({ m, busy, run, reload }: { m: VideoMedia; busy: boolean; run: (fn: () => Promise<unknown>, ok?: string) => Promise<void>; reload: () => Promise<void> }) {
  const visual = m.kind === "clip" || m.kind === "photo";
  const info = m.kind === "photo" ? (m.summary || (m.dims ? `${m.dims[0]}×${m.dims[1]}` : ""))
    : m.kind === "clip" ? [duration(m.seconds), m.audio === false ? "sans son" : (m.talk || 0) >= 2 ? `${m.talk} passages parlés` : "avec son", m.summary || ""].filter(Boolean).join(" · ")
    : m.kind === "music" ? [duration(m.seconds), m.bpm ? `${Math.round(m.bpm)} BPM` : ""].filter(Boolean).join(" · ")
    : m.kind === "voice" ? [duration(m.seconds), m.phrases ? `${m.phrases.length} phrases` : ""].filter(Boolean).join(" · ")
    : duration(m.seconds);
  const canWords = (m.kind === "voice" || (m.kind === "clip" && m.audio !== false && (m.talk || 0) >= 2)) && !m.words;   // un bruit de chantier continu n'a rien à sous-titrer
  return (
    <li className="vs-tile">
      <div className={`vs-thumb is-${m.kind}`}>
        {visual ? <ClipThumb id={m.id} start={m.kind === "clip" ? (m.looks?.[0]?.t ?? 0) : 0} /> : <span className="vs-ico" aria-hidden>{MEDIA_ICON[m.kind]}</span>}
        <span className="vs-kind">{MEDIA_ICON[m.kind]} {MEDIA_FR[m.kind]}</span>
        {!!m.words && <span className="vs-cc" title={`Sous-titres prêts : ${m.words} mots`}>CC</span>}
        <button type="button" className="vs-x" disabled={busy} aria-label={`Retirer ${m.name}`} title="Retirer"
          onClick={() => run(async () => { await net.videoMediaHide(m.id); await reload(); }, "Média retiré.")}>×</button>
      </div>
      <b className="vs-name" title={m.name}>{m.name}</b>
      {info && <small className="vs-info">{info}</small>}
      {(m.kind === "music" || m.kind === "voice") && (
        <button type="button" className="vs-mini" disabled={busy}
          title={m.kind === "music" ? "C'est en fait une voix off" : "C'est en fait une musique"}
          onClick={() => run(async () => { await net.videoMediaKind(m.id, m.kind === "music" ? "voice" : "music"); await reload(); }, "Type corrigé.")}>
          ↔ {m.kind === "music" ? "Voix off" : "Musique"}</button>
      )}
      {canWords && (
        <button type="button" className="vs-mini" disabled={busy}
          onClick={() => { if (window.confirm(`Créer les sous-titres de « ${m.name} » ? Le son part chez ElevenLabs (ton crédit, environ ${Math.max(1, Math.ceil(m.seconds / 60))} min de son).`))
            run(async () => { await net.videoMediaWords(m.id); await reload(); }, "Sous-titres prêts."); }}>Sous-titres</button>
      )}
    </li>
  );
}

/** Studio vidéo : on dépose ses médias (le type est reconnu tout seul), on dit ce qu'on veut si on veut, et l'IA monte la vidéo.
 *  Montage seulement : les outils IA payants ont été retirés du Studio (décision du patron). Rien n'est publié. */
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
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<VideoMedia[]>([]);
  const [autoWords, setAutoWords] = useState(true);
  const [sending, setSending] = useState<{ n: number; of: number; name: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  const reload = () => net.videoMedia().then((r) => { setItems(r.items); setAutoWords(r.auto_words !== false); }).catch(() => {});
  useEffect(() => {
    let alive = true;
    reload();
    net.videoDraft().then((d) => {   // scénario préparé dans le chat (outil plan_video) : ouvert une fois, prêt à relire et lancer
      if (!alive || !d.plan || !d.at) return;
      try { if (localStorage.getItem("unic.video.draft") === d.at) return; localStorage.setItem("unic.video.draft", d.at); } catch { /* ignoré */ }
      setBrief(d.brief || ""); setPlan(d.plan); setChanges(d.plan.changes ?? []);
      if (d.plan.spec?.format) setFmt(d.plan.spec.format);
      say("Scénario préparé dans le chat : relis-le, corrige si besoin, puis « Lancer la fabrication ».");
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const vidState = vid?.state;
  useEffect(() => {   // la fabrication se suit toute seule
    if (vidState !== "building") return;
    let cancelled = false;
    const timer = setInterval(() => { net.videoStatus().then((s) => { if (!cancelled) setVid(s); }).catch(() => {}); }, 10000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [vidState]);
  /** « Dépose tout ici » : plusieurs fichiers d'un coup, le serveur reconnaît le type de chacun. */
  const send = async (list: FileList | File[] | null) => {
    const files = Array.from(list || []);
    if (!files.length || sending) return;
    let ok = 0;
    for (const [i, f] of files.entries()) {
      setSending({ n: i + 1, of: files.length, name: f.name });
      try { await net.videoMediaAdd(f, "auto"); ok++; } catch (e: any) { say(`${f.name} : ${e.message || "envoi impossible"}`); }
    }
    setSending(null); await reload();
    if (ok) say(ok > 1 ? `${ok} médias ajoutés.` : "Média ajouté.");
  };
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
  const counts = items.reduce((a, m) => { a[m.kind] = (a[m.kind] || 0) + 1; return a; }, {} as Record<string, number>);
  return (
    <section className="card-box vs vs2">
      <label>Studio vidéo</label>
      <p className="hint">Ajoute tes médias, dis ce que tu veux (ou rien) : l'IA regarde tout et monte la vidéo. Rien n'est publié.</p>

      <div className={`vs-drop${drag ? " on" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}>
        <label className="vs-drop-btn">
          <span className="vs-drop-ico" aria-hidden>📥</span>
          <b>{sending ? `Envoi ${sending.n}/${sending.of}…` : "Dépose tout ici"}</b>
          <small>{sending ? sending.name : "Vidéos, photos, musique, voix off, animations — plusieurs à la fois"}</small>
          <input type="file" hidden multiple accept={ACCEPT_ALL} disabled={busy || !!sending} onChange={(e) => { send(e.target.files); e.currentTarget.value = ""; }} />
        </label>
      </div>
      {!!items.length && (
        <>
          <p className="vs-count">{(Object.keys(MEDIA_FR) as VideoMedia["kind"][]).filter((k) => counts[k]).map((k) => `${MEDIA_ICON[k]} ${counts[k]}`).join("  ")}</p>
          <ul className="vs-tiles">{items.map((m) => <MediaTile key={m.id} m={m} busy={busy} run={run} reload={reload} />)}</ul>
        </>
      )}

      <textarea className="vs-brief" rows={3} value={brief} onChange={(e) => setBrief(e.target.value)} maxLength={20000} aria-label="Ce que tu veux (facultatif)"
        placeholder="Dis ce que tu veux (facultatif). Ex. Pub de 30 s pour les JOJ avec mes vidéos, slogan à la fin." />
      <div className="vs-fmt" role="radiogroup" aria-label="Format de la vidéo">
        {([["vertical", "📱 9:16", "WhatsApp, TikTok, Reels"], ["horizontal", "🖥️ 16:9", "YouTube, écran"], ["square", "⬛ 1:1", "Facebook, Instagram"]] as const).map(([k, name, hint]) => (
          <button key={k} role="radio" aria-checked={fmt === k} title={hint} className={`chip${fmt === k ? " on" : ""}`} onClick={() => setFmt(k)}>{name}</button>
        ))}
      </div>
      <button className="btn btn-copper vs-go" disabled={busy || !!sending} onClick={() => propose()}>{planning ? "L'IA écrit le scénario…" : plan ? "🔄 Refaire le scénario" : "🎬 Créer ma vidéo"}</button>
      {planning && <p className="vs-status" role="status">L'IA regarde tes médias et écrit le scénario… Souvent moins d'une minute.</p>}

      <details className="vs-opts">
        <summary>Options</summary>
        <p className="vs-h">Ambiance des couleurs</p>
        <div className="vs-fmt" role="radiogroup" aria-label="Ambiance de la vidéo">
          {["auto", ...Object.keys(THEMES)].map((k) => (
            <button key={k} role="radio" aria-checked={theme === k} className={`chip${theme === k ? " on" : ""}`} onClick={() => setTheme(k)}>
              {k !== "auto" && <i className="vs-dot" style={{ background: THEMES[k].bg, boxShadow: `inset 0 0 0 3px ${THEMES[k].accent}` }} aria-hidden />}
              {k === "auto" ? "Auto" : THEMES[k].name}
            </button>
          ))}
        </div>
        <label className="vs-check"><input type="checkbox" checked={autoWords} disabled={busy}
          onChange={(e) => { const on = e.target.checked; run(async () => { setAutoWords((await net.videoMediaAutoWords(on)).auto_words); }, on ? "Sous-titres automatiques activés." : "Sous-titres seulement au clic."); }} />
          Sous-titres automatiques (vidéos parlées et voix off, crédit ElevenLabs)</label>
        <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setVid(await net.videoStatus()); })}>Où en est la vidéo ?</button>
      </details>

      {plan && shown && (
        <div className="vs-plan">
          {plan.understood && <div className="vs-understood"><b>Ce que j'ai compris</b>{plan.understood}</div>}
          {!!plan.assumptions?.length && (<><p className="vs-h">J'ai supposé — corrige-moi si c'est faux</p><ul className="vs-list">{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></>)}
          {!!plan.limits?.length && (<><p className="vs-h">Ce que le montage ne sait pas faire</p><ul className="vs-list">{plan.limits.map((a, i) => <li key={i}>{a}</li>)}</ul></>)}
          <p className="vs-sum"><b>{shown.scenes.length} scènes</b> · environ {duration(plan.seconds)}</p>
          <p className="vs-note">{plan.note}</p>
          {typeof shown.audio?.beat === "boolean" && (
            <label className="vs-check"><input type="checkbox" checked={shown.audio.beat} disabled={busy}
              onChange={(e) => { const on = e.target.checked; setPlan((p) => p && { ...p, spec: { ...p.spec, audio: { ...(p.spec.audio || {}), beat: on } } }); }} />
              Coupes au rythme de la musique</label>
          )}
          {typeof shown.captions === "boolean" && (
            <label className="vs-check"><input type="checkbox" checked={shown.captions} disabled={busy}
              onChange={(e) => { const on = e.target.checked; setPlan((p) => p && { ...p, spec: { ...p.spec, captions: on } }); }} />
              Sous-titres mot à mot sur la parole</label>
          )}
          <Storyboard spec={shown} onRemove={removeScene} busy={busy} />
          <p className="vs-h">Corriger le scénario</p>
          <textarea className="vs-fix" rows={2} value={fix} onChange={(e) => setFix(e.target.value)} maxLength={2000} aria-label="Corriger le scénario"
            placeholder="Ex. plus court, change la scène 3, mets la musique plus tôt…" />
          <div className="row-actions">
            <button className="btn btn-line btn-small" disabled={busy || !fix.trim()} onClick={() => propose(fix.trim())}>Corriger</button>
          </div>
          {changes.length > 0 && <p className="vs-note">Corrections appliquées : {changes.map((c, i) => `${i + 1}. ${c}`).join(" · ")}</p>}
          <button className="btn btn-copper vs-go" disabled={busy}
            onClick={() => {
              if (window.confirm("Lancer la fabrication de la vidéo ? Le temps dépend de sa durée ; une vidéo longue peut prendre beaucoup plus longtemps."))
                run(async () => { const r = await net.videoStart(shown); setPlan(null); setChanges([]); setVid({ state: "building", detail: r.note }); }, "Fabrication lancée.");
            }}>▶️ Lancer la fabrication</button>
        </div>
      )}
      {vid && <p className="vs-status" role="status">{vid.detail} {vid.url && <a href={vid.url} target="_blank" rel="noopener noreferrer">Détail</a>}</p>}
      {vid?.state === "failed" && vid.can_retry && (
        <button className="btn btn-copper" disabled={busy} onClick={() => run(async () => { const r = await net.videoRetry(); setVid({ state: r.ok ? "building" : "failed", detail: r.note }); }, "Montage relancé.")}>Relancer le montage</button>
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
