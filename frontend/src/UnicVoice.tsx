import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api, isNative } from "./api";
import * as I from "./Icons";
import { listenOnce } from "./listen";
import { audioRoute, getPhoneWhenLocked, getReadWhenLocked, notifApi, phone, wakeApi } from "./phone";
import { looksLikePhoneTask, runNotifCommand, type Notif } from "./notifs";
import { createSpeaker, ding, getVocalRate, say as sayRate, stop as stopSpeech } from "./speech";
import { HANGUP_RE, runPhoneIntent, type Intent } from "./unicPhone";

/** UniC vocal : on lui parle, il répond à voix haute. Rien n'est écrit à l'écran. Dire « stop » ou « merci » termine. */
type Phase = "idle" | "listening" | "thinking" | "speaking";
const LABEL: Record<Phase, string> = { idle: "Touche pour parler", listening: "Je t'écoute", thinking: "Je réfléchis…", speaking: "Je parle" };
const HEARING = "Je t'entends…";
const WAITING = "Un instant…";   // le micro n'est pas encore ouvert : on n'affiche « Je t'écoute » qu'au signal sonore
/** « mode interprète », « active la traduction en anglais » → ouvre l'interprète (la langue citée est préchoisie). */
const INTERP_RE = /interpr[èe]te|traducteur|mode traduction|(?:active|lance|ouvre|d[ée]marre)\s+(?:la\s+)?traduction/i;
const INTERP_LANGS: [RegExp, string][] = [[/anglais|english/i, "en"], [/arabe/i, "ar"], [/espagnol/i, "es"], [/portugais/i, "pt"], [/allemand/i, "de"], [/italien/i, "it"], [/turc/i, "tr"], [/chinois/i, "zh"], [/russe/i, "ru"], [/n[ée]erlandais|hollandais/i, "nl"], [/japonais/i, "ja"], [/hindi/i, "hi"]];
const END_RE = /^(stop|arr[êe]te|merci|c'est bon|c est bon|au revoir|ça suffit|ca suffit|fini|termin[ée])\b/i;

const say = (t: string) => sayRate(t, getVocalRate());   // UniC vocal parle à la vitesse choisie (1,25 par défaut)

export function UnicVoice() {
  const nav = useNavigate();
  const [phase, setPhase] = useState<Phase>("idle");
  const [err, setErr] = useState("");
  const [hearing, setHearing] = useState(false);
  const [ready, setReady] = useState(false);   // micro réellement ouvert
  const active = useRef(false);
  const cid = useRef<string | undefined>(undefined);
  const queue = useRef<{ items: Notif[]; index: number }>({ items: [], index: 0 });
  const failed = useRef(false);   // erreur affichée : l'écran reste ouvert pour qu'on la lise
  const manual = useRef(false);   // arrêt par un toucher : on ne ferme pas
  const interp = useRef("");   // l'interprète a été demandé à voix haute : on y va quand la conversation se termine
  const wake = useRef(!!(window as unknown as { __unicWake?: boolean }).__unicWake);   // ouvert par « Hey UniC »

  const end = () => { active.current = false; stopSpeech(); setPhase("idle"); };

  async function conversation() {
    let silent = 0;
    while (active.current) {
      setPhase("listening");
      setHearing(false);
      setReady(false);
      let heard = "";
      try { heard = await listenOnce(() => setHearing(true), () => setReady(true)); } catch (e: any) { failed.current = true; setErr(e?.message || "Micro indisponible"); return; }
      setHearing(false);
      if (!active.current) return;
      if (!heard) { if (++silent >= 3) { await say("Je ne t'entends pas. Touche la bille quand tu veux me parler."); return; } continue; }   // silence : on réécoute tout de suite, sans quitter
      silent = 0;
      ding();   // « j'ai entendu » : retour immédiat pendant que UniC réfléchit
      if (END_RE.test(heard.trim())) { await say("D'accord. À tout de suite."); return; }
      if (INTERP_RE.test(heard)) {   // l'interprète a son propre écran : il s'active seulement ici, sur demande
        if (wake.current) { setPhase("speaking"); await say("Ouvre l'application pour l'interprète."); continue; }
        const l = INTERP_LANGS.find(([re]) => re.test(heard))?.[1];
        setPhase("speaking"); await say("J'ouvre l'interprète. Touche qui parle.");
        interp.current = l ? `/interprete?lang=${l}` : "/interprete";
        return;
      }
      if (isNative && HANGUP_RE.test(heard)) {   // « coupe l'appel » : raccrocher tout de suite
        setPhase("speaking");
        try { await say((await phone.endCall()) ? "C'est fait, appel terminé." : "Il n'y a pas d'appel en cours."); }
        catch (e: any) { await say(e?.message || "Je n'ai pas pu raccrocher."); }
        continue;
      }
      setPhase("thinking");
      const locked = isNative ? await notifApi.locked().catch(() => true) : false;   // en cas de doute : verrouillé
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
        const it = looksLikePhoneTask(heard) ? await api.unicIntent(heard).catch(() => null) : null;   // pas d'aller-retour serveur si la phrase ne parle ni d'appel ni de message
        if (it && (it.action === "call" || it.action === "sms")) {   // tâche du téléphone : toujours confirmée à voix haute avant d'agir
          if (locked && !getPhoneWhenLocked()) { setPhase("speaking"); await say("Déverrouille le téléphone pour ça."); continue; }
          if (!isNative) { await say("Appeler et envoyer des messages marche seulement dans l'application Android."); continue; }
          setPhase("speaking");
          try {
            await runPhoneIntent(it as Intent, { say, listen: async () => { setPhase("listening"); setReady(false); const h = await listenOnce(undefined, () => setReady(true)); setPhase("speaking"); return h; }, phone,
              polish: async (t) => (await api.unicPolish(t).catch(() => ({ message: t }))).message });
          } catch (e: any) { await say(e?.message || "Je n'ai pas pu le faire."); }
          continue;
        }
        let speaker = createSpeaker();
        let started = false;
        const out = await api.chatStream({ message: heard, conversation_id: cid.current, voice: true, locked }, (ev) => {
          if (!active.current) { speaker.cancel(); return; }
          if (ev.t === "delta") { if (!started) { started = true; setPhase("speaking"); } speaker.push(ev.text || ""); }   // il parle dès la première phrase
          else if (ev.t === "reset") { speaker.cancel(); speaker = createSpeaker(); started = false; }
        });
        cid.current = out.conversation_id;
        if (!out.streamed) speaker.push(out.message?.content || "");
        setPhase("speaking");
        await speaker.finish();
        continue;
      } catch (e: any) { reply = e?.message || "Je n'arrive pas à joindre le serveur."; }
      if (!active.current) return;
      setPhase("speaking");
      await say(reply);
    }
  }

  const loop = async () => {
    try { await conversation(); } finally { end(); if (interp.current) { const to = interp.current; interp.current = ""; nav(to); return; } if (wake.current && !failed.current && !manual.current) wakeApi.finish().catch(() => {}); }   // « Hey UniC » : on referme et on remet l'écoute
  };

  const begin = () => { setErr(""); failed.current = false; manual.current = false; active.current = true; loop().catch((e) => setErr(e?.message || "Erreur")); };
  const toggle = () => { if (active.current) { manual.current = true; end(); } else begin(); };
  const close = () => { end(); if (wake.current) wakeApi.finish().catch(() => {}); else nav(-1); };

  useEffect(() => {
    // téléphone verrouillé : cet écran (seulement lui) peut s'afficher par-dessus l'écran de verrouillage
    if (isNative) { notifApi.lockScreenMode(true).catch(() => {}); audioRoute(true); }   // casque Bluetooth / AirPods : micro du casque
    const auto = wake.current ? window.setTimeout(() => { if (!active.current) begin(); }, 350) : 0;   // « Hey UniC » : il écoute tout de suite
    return () => { window.clearTimeout(auto); active.current = false; stopSpeech(); if (isNative) { notifApi.lockScreenMode(false).catch(() => {}); audioRoute(false); } };
  }, []);

  return createPortal(
    <div className={`unic-voice ${phase === "listening" && !ready ? "thinking" : phase}${hearing ? " hearing" : ""}`} role="application" aria-label="UniC vocal">
      <button className="unic-close" onClick={close} aria-label="Fermer"><I.Close size={24} /></button>
      <button className="unic-orb" onClick={toggle} aria-label={LABEL[phase]}>
        <span className="unic-ring r1" /><span className="unic-ring r2" /><span className="unic-core"><I.Mic size={44} /></span>
      </button>
      <p className="unic-state" role="status" aria-live="polite">{phase === "listening" ? (hearing ? HEARING : ready ? LABEL.listening : WAITING) : LABEL[phase]}</p>
      {err && <p className="error" role="alert">{err}</p>}
    </div>,
    document.body,
  );
}
