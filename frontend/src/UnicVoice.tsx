import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api, isNative } from "./api";
import * as I from "./Icons";
import { getReadWhenLocked, notifApi, phone } from "./phone";
import { runNotifCommand, type Notif } from "./notifs";
import { say, stop as stopSpeech } from "./speech";
import { runPhoneIntent, type Intent } from "./unicPhone";

/** UniC vocal : on lui parle, il répond à voix haute. Rien n'est écrit à l'écran. Dire « stop » ou « merci » termine. */
type Phase = "idle" | "listening" | "thinking" | "speaking";
const LABEL: Record<Phase, string> = { idle: "Touche pour parler", listening: "Je t'écoute", thinking: "Je réfléchis…", speaking: "Je parle" };
const END_RE = /^(stop|arr[êe]te|merci|c'est bon|c est bon|au revoir|ça suffit|ca suffit|fini|termin[ée])\b/i;

/** Une écoute : rend ce que le patron a dit ("" si silence). Plugin Android ou reconnaissance du navigateur. */
async function listenOnce(): Promise<string> {
  if (isNative) {
    const { SpeechRecognition } = await import("@capacitor-community/speech-recognition");
    const { available } = await SpeechRecognition.available();
    if (!available) throw new Error("Reconnaissance vocale absente sur ce téléphone.");
    const perm = await SpeechRecognition.requestPermissions();
    if (perm.speechRecognition !== "granted") throw new Error("Micro refusé : autorise-le dans Réglages › Applis › UniC AI › Autorisations.");
    await SpeechRecognition.removeAllListeners();
    return new Promise<string>((resolve) => {
      let heard = "", done = false;
      const finish = () => { if (done) return; done = true; SpeechRecognition.removeAllListeners().catch(() => {}); resolve(heard.trim()); };
      SpeechRecognition.addListener("partialResults", (d: { matches: string[] }) => { if (d.matches?.[0]) heard = d.matches[0]; });
      SpeechRecognition.addListener("listeningState", (d: { status: "started" | "stopped" }) => { if (d.status === "stopped") setTimeout(finish, 700); });
      SpeechRecognition.start({ language: "fr-FR", partialResults: true, popup: false, maxResults: 1 }).catch(finish);
      setTimeout(finish, 15000);
    });
  }
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SR) throw new Error("Dictée indisponible sur ce navigateur.");
  return new Promise<string>((resolve) => {
    const r = new SR();
    r.lang = "fr-FR"; r.interimResults = false; r.maxAlternatives = 1;
    let text = "";
    r.onresult = (e: any) => { text = Array.from(e.results).map((x: any) => x[0].transcript).join(" "); };
    r.onend = () => resolve(text.trim());
    r.onerror = () => resolve(text.trim());
    r.start();
    setTimeout(() => { try { r.stop(); } catch { /* déjà arrêté */ } }, 15000);
  });
}

export function UnicVoice() {
  const nav = useNavigate();
  const [phase, setPhase] = useState<Phase>("idle");
  const [err, setErr] = useState("");
  const active = useRef(false);
  const cid = useRef<string | undefined>(undefined);
  const queue = useRef<{ items: Notif[]; index: number }>({ items: [], index: 0 });

  const end = () => { active.current = false; stopSpeech(); setPhase("idle"); };

  async function conversation() {
    let silent = 0;
    while (active.current) {
      setPhase("listening");
      let heard = "";
      try { heard = await listenOnce(); } catch (e: any) { setErr(e?.message || "Micro indisponible"); return; }
      if (!active.current) return;
      if (!heard) { if (++silent >= 2) { await say("Je suis là si tu as besoin."); return; } continue; }
      silent = 0;
      if (END_RE.test(heard.trim())) { await say("D'accord. À tout de suite."); return; }
      setPhase("thinking");
      let reply = "";
      try {
        if (isNative) {   // notifications : « qu'est-ce que j'ai reçu », « lis-moi le message » (tout reste sur le téléphone)
          let handled = false;
          setPhase("speaking");
          try { handled = await runNotifCommand(heard, { say, api: notifApi, readWhenLocked: getReadWhenLocked(), queue: queue.current }); }
          catch (e: any) { await say(e?.message || "Je n'ai pas pu lire tes notifications."); handled = true; }
          if (handled) continue;
          setPhase("thinking");
        }
        const it = await api.unicIntent(heard).catch(() => null);
        if (it && (it.action === "call" || it.action === "sms")) {   // tâche du téléphone : toujours confirmée à voix haute avant d'agir
          if (!isNative) { await say("Appeler et envoyer des messages marche seulement dans l'application Android."); continue; }
          setPhase("speaking");
          try {
            await runPhoneIntent(it as Intent, { say, listen: async () => { setPhase("listening"); const h = await listenOnce(); setPhase("speaking"); return h; }, phone,
              polish: async (t) => (await api.unicPolish(t).catch(() => ({ message: t }))).message });
          } catch (e: any) { await say(e?.message || "Je n'ai pas pu le faire."); }
          continue;
        }
        const out = await api.chatStream({ message: heard, conversation_id: cid.current, voice: true }, () => {});
        cid.current = out.conversation_id;
        reply = out.message?.content || "";
      } catch (e: any) { reply = e?.message || "Je n'arrive pas à joindre le serveur."; }
      if (!active.current) return;
      setPhase("speaking");
      await say(reply);
    }
  }

  const loop = async () => { try { await conversation(); } finally { end(); } };

  const toggle = () => {
    if (active.current) { end(); return; }
    setErr(""); active.current = true; loop().catch((e) => setErr(e?.message || "Erreur"));
  };

  useEffect(() => {
    // téléphone verrouillé : cet écran (seulement lui) peut s'afficher par-dessus l'écran de verrouillage
    if (isNative) notifApi.lockScreenMode(true).catch(() => {});
    return () => { active.current = false; stopSpeech(); if (isNative) notifApi.lockScreenMode(false).catch(() => {}); };
  }, []);

  return createPortal(
    <div className={`unic-voice ${phase}`} role="application" aria-label="UniC vocal">
      <button className="unic-close" onClick={() => { end(); nav(-1); }} aria-label="Fermer"><I.Close size={24} /></button>
      <button className="unic-orb" onClick={toggle} aria-label={LABEL[phase]}>
        <span className="unic-ring r1" /><span className="unic-ring r2" /><span className="unic-core"><I.Mic size={44} /></span>
      </button>
      <p className="unic-state" role="status" aria-live="polite">{LABEL[phase]}</p>
      {err && <p className="error" role="alert">{err}</p>}
    </div>,
    document.body,
  );
}
