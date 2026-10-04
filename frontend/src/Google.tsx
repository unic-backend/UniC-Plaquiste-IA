import { useEffect, useRef, useState } from "react";
import * as I from "./Icons";
import { isNative, net, type GOptimize, type GPlan } from "./api";

const cp = async (t: string) => { try { await navigator.clipboard.writeText(t); return true; } catch { return false; } };

/** Rappel local (téléphone) tous les 4 jours à 9 h, reprogrammé à chaque publication. */
async function scheduleReminders(on: boolean): Promise<string> {
  if (!isNative) return "Les rappels fonctionnent dans l'appli Android.";
  const { LocalNotifications } = await import("@capacitor/local-notifications");
  const ids = Array.from({ length: 20 }, (_, i) => 4100 + i);
  await LocalNotifications.cancel({ notifications: ids.map((id) => ({ id })) }).catch(() => {});
  if (!on) return "Rappels désactivés.";
  const perm = await LocalNotifications.requestPermissions();
  if (perm.display !== "granted") return "Notifications refusées : autorise-les dans Réglages › Applis › UniC AI.";
  const first = new Date();
  first.setHours(9, 0, 0, 0);
  const notifications = ids.map((id, i) => {
    const at = new Date(first.getTime() + (i + 1) * 4 * 86_400_000);
    return { id, title: "Fiche Google", body: "C'est le jour de publier une photo de chantier sur ta fiche Google.", schedule: { at, allowWhileIdle: true } };
  });
  await LocalNotifications.schedule({ notifications });
  return "Rappel programmé : tous les 4 jours à 9 h.";
}

/** Photo + texte vers l'appli de partage (Google Maps / Profil d'établissement, WhatsApp…). */
export async function sharePhoto(photo: File | null, text: string, app = "Google Maps / Profil d'établissement", title = "Publication fiche Google"): Promise<string> {
  await cp(text);   // beaucoup d'applis ignorent le texte quand une image est jointe : il est déjà copié
  if (!isNative) return "Texte copié. Ajoute la photo dans l'appli.";
  const { Share } = await import("@capacitor/share");
  let files: string[] | undefined;
  if (photo) {
    const { Filesystem, Directory } = await import("@capacitor/filesystem");
    const data: string = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(String(fr.result).split(",")[1] || "");
      fr.onerror = () => rej(new Error("Photo illisible"));
      fr.readAsDataURL(photo);
    });
    const path = `publication-${Date.now()}.jpg`;
    await Filesystem.writeFile({ path, data, directory: Directory.Cache });
    files = [(await Filesystem.getUri({ path, directory: Directory.Cache })).uri];
  }
  await Share.share({ title, text, files, dialogTitle: "Publier sur…" });
  return `Partage ouvert. Choisis ${app} ; le texte est déjà copié.`;
}

const API_REQUEST = `Business: UniC Plaquiste - drywall, false ceilings, partitions, painting and interior finishing, Dakar, Senegal
Website: https://www.unicplaquiste.com
Google Business Profile: https://maps.app.goo.gl/fKvNLhN1r3U88gsv9
Contact e-mail: unicplaquiste@gmail.com

Use case: UniC Plaquiste requests Basic API access for its own, single business location. We are building a private internal assistant used only by the business owner to: (1) publish Google Posts with photos on our own listing about every 4 days, (2) read and reply to customer reviews on our own listing, and (3) keep our own listing information (description, services, Q&A) up to date. Every post and every reply is reviewed and approved by the owner before it is sent. We do not manage third-party listings, we do not resell or share Business Profile data, and we store only an OAuth refresh token for the owner's account, encrypted on our server. Expected volume: a few API calls per day.`;

export function FicheGoogle() {
  const [plan, setPlan] = useState<GPlan | null>(null);
  const [err, setErr] = useState("");
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [opt, setOpt] = useState<GOptimize | null>(null);
  const [remind, setRemind] = useState<boolean>(() => { try { return localStorage.getItem("gbp-remind") === "1"; } catch { return false; } });
  const camRef = useRef<HTMLInputElement>(null);

  const say = (m: string) => { setToast(m); setTimeout(() => setToast(""), 4000); };
  const load = () => net.gPlan().then((p) => { setPlan(p); setText(p.draft?.body ?? ""); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!photo) { setPreview(""); return; }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };

  if (err) return <div className="page"><div className="page-inner"><p className="error">{err}</p></div></div>;
  if (!plan) return <div className="page"><div className="page-inner"><p className="hint">Chargement…</p></div></div>;
  const draft = plan.draft;
  const pct = Math.min(100, Math.round((plan.published_last_30_days / Math.max(1, plan.target_last_30_days)) * 100));
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Fiche Google</h1>
        <p className="lede">Une publication avec photo tous les {plan.cadence_days} jours, des mots-clés de Dakar et une fiche complète : ce qui fait monter une fiche locale.</p>

        <section className={`card-box ${plan.due ? "warn" : ""}`}>
          <label>Publication du jour</label>
          <div className="big-number" style={{ fontSize: 26 }}>
            {plan.due ? "À publier aujourd'hui" : `Prochaine le ${new Date(plan.next_due_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`}
          </div>
          <div className="meter"><i style={{ width: `${pct}%` }} /></div>
          <p className="hint">
            {plan.last_published_at ? `Dernière il y a ${plan.days_since} jour(s). ` : "Aucune publication encore. "}
            {plan.published_last_30_days}/{plan.target_last_30_days} sur 30 jours · thème conseillé : {plan.theme.label}
          </p>
          <div className="toolbar">
            <input placeholder="Sujet (facultatif) : ex. plafond salon à Mermoz" value={topic} onChange={(e) => setTopic(e.target.value)} />
            <button className="btn btn-copper" disabled={busy || !plan.ai}
              onClick={() => run(async () => { await net.gPlanDraft(topic); await load(); })}>
              <I.Sparkle size={16} /> {draft ? "Nouvelle proposition" : "Rédiger la publication"}
            </button>
          </div>
          {!plan.ai && <p className="error">Claude est indisponible : impossible de rédiger.</p>}
        </section>

        {draft && (
          <section className="card-box">
            <label>{draft.title || "Brouillon"}</label>
            <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} />
            <p className="hint">{text.length}/1500 caractères</p>
            {draft.photo_brief && (
              <div className="photo-brief"><I.Camera size={18} /><span><b>Photo à prendre :</b> {draft.photo_brief}</span></div>
            )}
            {preview && <img className="photo-preview" src={preview} alt="Photo choisie" />}
            <div className="toolbar">
              <button className="btn btn-line btn-small" onClick={() => camRef.current?.click()}><I.Camera size={16} /> {photo ? "Changer la photo" : "Prendre / choisir la photo"}</button>
              <button className="btn btn-line btn-small" onClick={async () => say((await cp(text)) ? "Texte copié." : "Copie impossible.")}><I.Copy size={16} /> Copier le texte</button>
            </div>
            <div className="toolbar">
              <button className="btn btn-copper" disabled={busy || text.trim().length < 20}
                onClick={() => run(async () => { if (text !== draft.body) await net.editPost(draft.id, text); say(await sharePhoto(photo, text)); })}>
                Partager vers Google
              </button>
              <button className="btn btn-line" disabled={busy}
                onClick={() => run(async () => {
                  if (text !== draft.body) await net.editPost(draft.id, text);
                  await net.gPlanDone(draft.id);
                  setPhoto(null);
                  await load();
                  if (remind) await scheduleReminders(true).catch(() => {});
                  say("Bravo : compteur de 4 jours relancé.");
                })}>
                <I.Check size={16} /> J'ai publié
              </button>
            </div>
            <p className="hint">{plan.auto_publish_note}</p>
            <input ref={camRef} className="sr-only" type="file" accept="image/*" capture="environment" onChange={(e) => { setPhoto(e.target.files?.[0] ?? null); e.target.value = ""; }} />
          </section>
        )}

        <section className="card-box">
          <label>Rappel</label>
          <div className="toolbar">
            <button className={`mode-chip ${remind ? "on" : ""}`} aria-pressed={remind}
              onClick={() => run(async () => {
                const next = !remind;
                const m = await scheduleReminders(next);
                setRemind(next && isNative);
                try { localStorage.setItem("gbp-remind", next && isNative ? "1" : "0"); } catch { /* stockage indisponible */ }
                say(m);
              })}>
              {remind ? "Rappel actif : tous les 4 jours, 9 h" : "Me rappeler tous les 4 jours"}
            </button>
          </div>
        </section>

        <section className="card-box">
          <label>Mots-clés à utiliser (touche pour copier)</label>
          <p className="hint">Recherches visées</p>
          <div className="kw">{plan.keywords.recherches.map((k) => <button key={k} onClick={async () => say((await cp(k)) ? `« ${k} » copié.` : "Copie impossible.")}>{k}</button>)}</div>
          <p className="hint">Quartiers et villes</p>
          <div className="kw">{plan.keywords.zones.map((k) => <button key={k} onClick={async () => say((await cp(k)) ? `« ${k} » copié.` : "Copie impossible.")}>{k}</button>)}</div>
          <p className="hint">Catégories à vérifier dans ta fiche : {plan.keywords.categories.join(" · ")}</p>
        </section>

        <section className="card-box">
          <label>Améliorer la fiche</label>
          <p className="hint">L'IA rédige la description, les services, les questions-réponses et les catégories à coller dans Google. Rien n'est modifié chez Google.</p>
          <button className="btn btn-copper" disabled={busy || !plan.ai}
            onClick={() => run(async () => setOpt(await net.gOptimize()))}>
            <I.Sparkle size={16} /> Préparer les textes de ma fiche
          </button>
          {opt && (
            <div className="opt">
              <h3>Description ({opt.description.length}/750)</h3>
              <p className="post-body">{opt.description}</p>
              <button className="btn btn-ghost btn-small" onClick={async () => say((await cp(opt.description)) ? "Description copiée." : "Copie impossible.")}><I.Copy size={15} /> Copier</button>
              {opt.categories && <><h3>Catégories</h3><p className="post-body">{opt.categories.join(" · ")}</p></>}
              {opt.services?.map((s) => (
                <div key={s.nom} className="opt-row"><b>{s.nom}</b><span>{s.texte}</span></div>
              ))}
              {opt.questions?.map((q) => (
                <div key={q.q} className="opt-row"><b>{q.q}</b><span>{q.r}</span></div>
              ))}
            </div>
          )}
        </section>

        <section className="card-box">
          <label>Ma fiche est-elle complète ? {plan.checklist.done}/{plan.checklist.total}</label>
          <div className="meter"><i style={{ width: `${(plan.checklist.done / plan.checklist.total) * 100}%` }} /></div>
          {plan.checklist.items.map((c) => (
            <label key={c.id} className="check-row">
              <input type="checkbox" checked={c.done}
                onChange={(e) => run(async () => { const ck = await net.gCheck(c.id, e.target.checked); setPlan((p) => (p ? { ...p, checklist: ck } : p)); })} />
              <span>{c.label}</span>
            </label>
          ))}
        </section>
        <section className="card-box">
          <label>Publier automatiquement (plus tard)</label>
          <p className="hint">
            {plan.api_configured ? "Accès Google configuré." : "Google doit d'abord t'accorder l'accès à son API : c'est une demande à faire une fois, sur ton compte. Délai : non garanti. En attendant, tu publies à la main (20 secondes)."}
          </p>
          {!plan.api_configured && (
            <>
              <ol className="steps">
                <li>Crée un projet sur <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener noreferrer">Google Cloud</a> (nom : UniC AI) ; note son numéro.</li>
                <li>Ouvre la <a href="https://developers.google.com/my-business/content/prereqs" target="_blank" rel="noopener noreferrer">page des prérequis</a> → « request access » et colle le texte ci-dessous.</li>
                <li>Quand Google répond oui, reviens ici : je te guide pour la connexion.</li>
              </ol>
              <button className="btn btn-line" onClick={async () => say((await cp(API_REQUEST)) ? "Texte de la demande copié." : "Copie impossible.")}>
                <I.Copy size={16} /> Copier le texte de la demande
              </button>
            </>
          )}
        </section>
        {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    </div>
  );
}
