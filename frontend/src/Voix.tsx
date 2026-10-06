import { useEffect, useRef, useState } from "react";
import * as I from "./Icons";
import { isNative, net } from "./api";
import { crashApi, getPhoneWhenLocked, getReadWhenLocked, notifApi, setPhoneWhenLocked, setReadWhenLocked, wakeApi } from "./phone";
import type { WakeInfo } from "./phone";

const WAKE_STATE: Record<string, string> = {
  loading: "Préparation du moteur d'écoute…", listening: "UniC écoute le mot d'appel.", busy: "UniC est ouvert.",
  missing: "Moteur d'écoute absent de cette version.", error: "L'écoute s'est arrêtée (micro occupé ?). Réactive-la.", off: "Écoute arrêtée.",
};
import { canSpeakOnDevice, clearCache, deviceVoices, getPref, getVocalRate, setPref, setVocalRate, speakDevice, stop, type VoicePref } from "./speech";

const SAMPLE = "Bonjour patron, voici ma voix. Le devis est prêt, je te lis les détails.";
type EVoice = Awaited<ReturnType<typeof net.voiceList>>[number];

/** Page Voix : choisir la voix de lecture (téléphone ou ElevenLabs) et cloner sa propre voix. */
export function Voix() {
  const [pref, setP] = useState<VoicePref>(getPref());
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(deviceVoices());
  const [st, setSt] = useState<{ configured: boolean; voice_id: string; limits: string } | null>(null);
  const [eVoices, setEVoices] = useState<EVoice[]>([]);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const say = (m: string) => { setMsg(m); setTimeout(() => setMsg(""), 4000); };
  const upd = (p: Partial<VoicePref>) => setP(setPref(p));
  const [notifOn, setNotifOn] = useState<boolean | null>(null);
  const [lockRead, setLockRead] = useState(getReadWhenLocked());
  const [wake, setWake] = useState<WakeInfo | null>(null);
  const [crash, setCrash] = useState<{ text: string; time: number } | null>(null);
  const [phoneLock, setPhoneLock] = useState(getPhoneWhenLocked());
  const [vocal, setVocal] = useState(getVocalRate());
  useEffect(() => {
    if (!isNative) return;
    const check = () => {
      notifApi.enabled().then(setNotifOn).catch(() => setNotifOn(false));
      wakeApi.status().then(setWake).catch(() => setWake(null));
      crashApi.last().then((c) => setCrash(c.text ? c : null)).catch(() => setCrash(null));
    };
    check();
    document.addEventListener("visibilitychange", check);   // retour des réglages Android : on relit l'état
    return () => document.removeEventListener("visibilitychange", check);
  }, []);

  useEffect(() => {
    const load = () => setVoices(deviceVoices());
    load();
    window.speechSynthesis?.addEventListener?.("voiceschanged", load);
    return () => { window.speechSynthesis?.removeEventListener?.("voiceschanged", load); stop(); };
  }, []);
  const refresh = async () => {
    try {
      const s = await net.voiceStatus();
      setSt(s);
      setEVoices(s.configured ? await net.voiceList() : []);
    } catch (e: any) { say(e.message); }
  };
  useEffect(() => { refresh(); }, []);

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Voix</h1>
        <p className="lede">Le bouton <I.Speaker size={14} /> sous chaque réponse la lit à voix haute.</p>

        {isNative && (
          <section className="card-box">
            <h3>UniC vocal : lire mes notifications</h3>
            <p className="hint">Dis « qu'est-ce que j'ai reçu ? » puis « lis-moi le message ». WhatsApp, SMS, Instagram, Facebook, Reddit… Tout reste sur ton téléphone.</p>
            <p className={notifOn ? "hint ic" : "error"}>{notifOn === null ? "Vérification…" : notifOn ? <><I.Check size={16} /> Accès aux notifications accordé</> : "Accès aux notifications non accordé."}</p>
            {!notifOn && <button className="btn btn-copper btn-small" onClick={() => notifApi.openSettings().catch((e) => say(e.message))}>Autoriser l'accès</button>}
            {!notifOn && <p className="hint">Si Android refuse (« paramètre restreint ») : Réglages › Applis › UniC AI › menu ⋮ › « Autoriser les paramètres restreints », puis recommence.</p>}
            <label><input type="checkbox" checked={lockRead} onChange={(e) => { setReadWhenLocked(e.target.checked); setLockRead(e.target.checked); }} /> Lire même quand le téléphone est verrouillé</label>
          </section>
        )}

        {isNative && crash && (
          <section className="card-box">
            <h3>Dernier plantage de l'appli</h3>
            <p className="hint">{new Date(crash.time).toLocaleString("fr-FR")} — envoie une capture de ce texte à l'assistant pour qu'il corrige.</p>
            <pre className="hint" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, maxHeight: 220, overflow: "auto" }}>{crash.text}</pre>
            <button className="btn btn-small" onClick={() => crashApi.clear().then(() => setCrash(null)).catch((e) => say(e.message))}>Effacer</button>
          </section>
        )}

        {isNative && wake && (
          <section className="card-box">
            <h3>« Hey UniC » : sans ouvrir l'appli</h3>
            <p className="hint">Dis « Hey UniC » (ou « OK UniC ») : UniC s'ouvre et t'écoute, même écran verrouillé. L'écoute du mot d'appel reste sur le téléphone : rien n'est enregistré ni envoyé avant le mot d'appel.</p>
            {!wake.modelBundled
              ? <p className="error">Cette version n'embarque pas le moteur du mot d'appel.</p>
              : <label><input type="checkbox" checked={wake.enabled} disabled={busy} onChange={(e) => run(async () => setWake(e.target.checked ? await wakeApi.start() : await wakeApi.stop()))} /> Activer « Hey UniC » (une notification reste affichée : c'est normal)</label>}
            {wake.enabled && <p className={wake.state === "listening" ? "hint ic" : "hint"}>{WAKE_STATE[wake.state] || wake.state}</p>}
            <p className={wake.overlay ? "hint ic" : "error"}>{wake.overlay ? <><I.Check size={16} /> Ouverture automatique autorisée</> : "Ouverture automatique non autorisée : UniC ne pourra s'ouvrir seul que via une notification à toucher."}</p>
            {!wake.overlay && <button className="btn btn-copper btn-small" onClick={() => wakeApi.openOverlay().catch((e) => say(e.message))}>Autoriser « Afficher par-dessus les autres applis »</button>}
            <p className={wake.battery ? "hint ic" : "error"}>{wake.battery ? <><I.Check size={16} /> Batterie : pas de mise en veille d'UniC</> : "Batterie : Android peut couper l'écoute. Choisis « Sans restriction » pour UniC."}</p>
            {!wake.battery && <button className="btn btn-copper btn-small" onClick={() => wakeApi.openBattery().catch((e) => say(e.message))}>Autoriser en arrière-plan</button>}
            <label><input type="checkbox" checked={phoneLock} onChange={(e) => { setPhoneWhenLocked(e.target.checked); setPhoneLock(e.target.checked); }} /> Appeler et écrire des SMS même téléphone verrouillé (déconseillé : n'importe qui près de toi peut le dire)</label>
            <p className="hint">Verrouillé, UniC n'a jamais accès aux clients, devis, factures ni prix. Après un redémarrage, ouvre l'appli une fois pour relancer l'écoute (Android l'impose).</p>
          </section>
        )}

        <section className="card-box">
          <label>Vitesse de UniC vocal</label>
          <input type="range" min={0.8} max={1.6} step={0.05} value={vocal} onChange={(e) => { const v = Number(e.target.value); setVocal(v); setVocalRate(v); }} aria-label="Vitesse de UniC vocal" />
          <p className="hint">{vocal.toFixed(2).replace(/0$/, "")} fois la vitesse normale{vocal === 1.25 ? " (réglage conseillé)" : ""}</p>
        </section>

        <section className="card-box">
          <label>Moteur de lecture</label>
          <div className="seg" role="group" aria-label="Moteur de lecture">
            <button className={pref.engine === "device" ? "on" : ""} onClick={() => { stop(); upd({ engine: "device" }); }}>Téléphone</button>
            <button className={pref.engine === "eleven" ? "on" : ""} onClick={() => { stop(); upd({ engine: "eleven" }); }}>ElevenLabs</button>
          </div>
          <label>Vitesse</label>
          <input type="range" min={0.7} max={1.3} step={0.05} value={pref.rate} onChange={(e) => upd({ rate: Number(e.target.value) })} aria-label="Vitesse de lecture" />
          <p className="hint">{pref.rate === 1 ? "Normale" : pref.rate < 1 ? "Plus lente" : "Plus rapide"}</p>
        </section>

        <section className="card-box">
          <label>Voix du téléphone (gratuit)</label>
          {!canSpeakOnDevice() || voices.length === 0 ? (
            <>
              <p className="hint">Voix par défaut du téléphone (français). Pas de liste à choisir ici : change la voix dans Réglages › Synthèse vocale.</p>
              <button className="btn btn-line btn-small" onClick={() => speakDevice(SAMPLE, "", pref.rate)}><I.Speaker size={14} /> Tester la voix du téléphone</button>
            </>
          ) : (
            <div className="voice-list">
              {voices.map((v) => (
                <div key={v.voiceURI} className={`voice-row ${pref.deviceVoice === v.voiceURI ? "on" : ""}`}>
                  <button className="voice-pick" onClick={() => upd({ deviceVoice: v.voiceURI, engine: "device" })}>
                    <b>{v.name}</b><span>{v.lang}{v.localService ? " · hors ligne" : ""}</span>
                  </button>
                  <button className="btn btn-line btn-small" onClick={() => speakDevice(SAMPLE, v.voiceURI, pref.rate)}><I.Speaker size={14} /> Test</button>
                </div>
              ))}
            </div>
          )}
          <p className="hint">Le téléphone ne dit pas si une voix est d'homme ou de femme : teste-les et garde celle que tu préfères.</p>
        </section>

        <section className="card-box">
          <label>ElevenLabs : voix naturelles et ta voix</label>
          {st && !st.configured && (
            <>
              <ol className="steps">
                <li>Crée un compte sur <b>elevenlabs.io</b> (gratuit pour les voix prêtes).</li>
                <li>Profil → <b>Clés API</b> → crée une clé et copie-la.</li>
                <li>Colle-la ici.</li>
              </ol>
              <input type="password" autoComplete="off" placeholder="Clé ElevenLabs" value={key} onChange={(e) => setKey(e.target.value)} />
              <button className="btn btn-copper" disabled={busy || key.trim().length < 20}
                onClick={() => run(async () => { await net.voiceConnect(key); setKey(""); await refresh(); upd({ engine: "eleven" }); }, "ElevenLabs connecté.")}>
                Connecter
              </button>
            </>
          )}
          {st?.configured && (
            <>
              <p className="post-body"><I.Check size={16} /> Connecté</p>
              <div className="voice-list">
                {eVoices.map((v) => (
                  <div key={v.id} className={`voice-row ${st.voice_id === v.id ? "on" : ""}`}>
                    <button className="voice-pick" disabled={busy}
                      onClick={() => run(async () => { await net.voiceSelect(v.id); clearCache(); upd({ engine: "eleven" }); await refresh(); })}>
                      <b>{v.mine ? "★ " : ""}{v.name}</b>
                      <span>{v.mine ? "Ta voix" : v.gender === "female" ? "Femme" : v.gender === "male" ? "Homme" : v.category}{v.accent ? ` · ${v.accent}` : ""}</span>
                    </button>
                    {v.preview && <button className="btn btn-line btn-small" onClick={() => { stop(); new Audio(v.preview).play().catch(() => {}); }}><I.Speaker size={14} /> Test</button>}
                    {v.mine && <button className="btn btn-line btn-small" disabled={busy}
                      onClick={() => { if (window.confirm(`Supprimer la voix « ${v.name} » chez ElevenLabs ?`)) run(async () => { await net.voiceDelete(v.id); clearCache(); await refresh(); }, "Voix supprimée."); }}>Supprimer</button>}
                  </div>
                ))}
              </div>
              <Cloner busy={busy} run={run} onDone={async () => { clearCache(); upd({ engine: "eleven" }); await refresh(); }} />
              <button className="btn btn-ghost btn-small" disabled={busy}
                onClick={() => { if (window.confirm("Déconnecter ElevenLabs ? La clé sera effacée du serveur.")) run(async () => { await net.voiceDisconnect(); clearCache(); upd({ engine: "device" }); await refresh(); }, "ElevenLabs déconnecté."); }}>
                Déconnecter
              </button>
            </>
          )}
          {st && <p className="hint">{st.limits}</p>}
        </section>
        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    </div>
  );
}

/** Enregistre ~40 s de la voix du patron (ou un fichier audio) et la clone. */
function Cloner({ busy, run, onDone }: { busy: boolean; run: (fn: () => Promise<unknown>, ok?: string) => Promise<void>; onDone: () => Promise<void> }) {
  const [name, setName] = useState("Ma voix");
  const [own, setOwn] = useState(false);
  const [blob, setBlob] = useState<{ data: Blob; name: string } | null>(null);
  const [rec, setRec] = useState(false);
  const [secs, setSecs] = useState(0);
  const [err, setErr] = useState("");
  const mr = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => { window.clearInterval(timer.current); mr.current?.stream.getTracks().forEach((t) => t.stop()); }, []);

  async function start() {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const r = new MediaRecorder(stream);
      r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = r.mimeType || "audio/webm";
        setBlob({ data: new Blob(chunks, { type }), name: `voix.${type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm"}` });
      };
      mr.current = r; r.start(); setRec(true); setSecs(0); setBlob(null);
      timer.current = window.setInterval(() => setSecs((s) => { if (s >= 90) { r.stop(); window.clearInterval(timer.current); setRec(false); } return s + 1; }), 1000);
    } catch {
      setErr("Micro indisponible. Autorise le micro pour UniC AI, ou choisis un fichier audio ci-dessous.");
    }
  }
  function end() { window.clearInterval(timer.current); mr.current?.state === "recording" && mr.current.stop(); setRec(false); }

  return (
    <div className="cloner">
      <label>Cloner ma voix</label>
      <p className="hint">Lis un texte à voix naturelle pendant <b>40 à 90 secondes</b>, au calme, sans musique. Plus c'est long et propre, plus la voix ressemble.</p>
      <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} aria-label="Nom de la voix" />
      <div className="row">
        {!rec ? <button className="btn btn-copper" onClick={start} disabled={busy}><I.Mic size={16} /> Enregistrer</button>
              : <button className="btn btn-copper rec-on" onClick={end}><I.Stop size={16} /> Arrêter ({secs} s)</button>}
        <label className="btn btn-line file-btn">Choisir un fichier
          <input type="file" accept="audio/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) setBlob({ data: f, name: f.name }); }} />
        </label>
      </div>
      {err && <p className="error">{err}</p>}
      {blob && !rec && (
        <>
          <audio controls src={URL.createObjectURL(blob.data)} className="sample" />
          <label className="check-row"><input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} />
            C'est ma propre voix (ou une personne qui m'y autorise).</label>
          <button className="btn btn-copper" disabled={busy || !own || !name.trim()}
            onClick={() => run(async () => { await net.voiceClone(name.trim(), blob.data, blob.name); setBlob(null); setOwn(false); await onDone(); }, "Voix créée et choisie.")}>
            Créer ma voix
          </button>
        </>
      )}
      <p className="hint">Le cloner demande un abonnement ElevenLabs payant. Ton enregistrement part chez ElevenLabs, pas ailleurs.</p>
    </div>
  );
}
