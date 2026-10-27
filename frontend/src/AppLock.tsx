import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as lock from "./codeLock";
import { signOut } from "./api";
import { notify } from "./feedback";

const secs = (ms: number) => (ms >= 60_000 ? `${Math.ceil(ms / 60_000)} min` : `${Math.ceil(ms / 1000)} s`);

/** Écran du code : posé par-dessus toute l'appli (rien n'est démonté : la conversation en cours reste là derrière). */
function LockScreen({ onOpen }: { onOpen: () => void }) {
  const len = lock.config()?.len || lock.MIN_LEN;
  const [pin, setPin] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(() => lock.waitMs());
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!wait) return;
    const t = window.setInterval(() => setWait(lock.waitMs()), 1000);
    return () => window.clearInterval(t);
  }, [wait > 0]);
  useEffect(() => { if (!wait) { setMsg(""); field.current?.focus(); } }, [wait]);
  const attempt = async (p: string) => {
    setBusy(true);
    const r = await lock.check(p);
    setBusy(false);
    if (r.ok) { onOpen(); return; }
    setPin("");
    setWait(r.waitMs);
    setMsg(r.waitMs ? "Trop d'essais." : "Code incorrect.");
    if (!r.waitMs) field.current?.focus();   // le clavier reste ouvert pour réessayer
  };
  const forgot = async () => {
    if (!window.confirm("Code oublié : UniC te déconnecte de cet appareil. Tu te reconnectes ensuite avec ton e-mail et ton mot de passe. Continuer ?")) return;
    lock.clear();
    await signOut();
    window.location.reload();
  };
  return createPortal(
    <div className="login app-lock" role="dialog" aria-modal="true" aria-label="Appli verrouillée">
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); if (lock.validPin(pin)) attempt(pin); }}>
        <h1>UniC AI</h1>
        <p>Entre ton code pour ouvrir l'appli.</p>
        <input ref={field} className="app-lock-pin" type="password" inputMode="numeric" pattern="[0-9]*" autoComplete="off" autoFocus
          aria-label="Code de l'appli" maxLength={lock.MAX_LEN} value={pin} readOnly={busy} disabled={wait > 0}
          onChange={(e) => {
            const v = e.target.value.replace(/\D/g, "").slice(0, lock.MAX_LEN);
            setPin(v);
            if (v.length === len) attempt(v);   // le code fait la longueur choisie : pas besoin d'appuyer sur un bouton
          }} />
        {(msg || wait > 0) && <p className="error" role="alert">{msg}{wait > 0 ? ` Réessaie dans ${secs(wait)}.` : ""}</p>}
        <button className="btn btn-copper" type="submit" disabled={busy || wait > 0 || !lock.validPin(pin)}>Déverrouiller</button>
        <button className="btn btn-line" type="button" onClick={forgot}>Code oublié ?</button>
      </form>
    </div>,
    document.body,
  );
}

/** Verrou à l'ouverture et au retour après le délai choisi. Sans code réglé : ne fait rien. */
export function AppLockGate() {
  const [locked, setLocked] = useState(() => lock.enabled());
  const hiddenAt = useRef<number | null>(null);
  useEffect(() => {
    const onVisibility = () => {
      const c = lock.config();
      if (!c) return;
      if (document.hidden) {
        hiddenAt.current = Date.now();
        if (c.idleMs === 0) setLocked(true);   // « tout de suite » : l'écran est déjà masqué quand on revient
        return;
      }
      if (lock.dueAfter(hiddenAt.current, Date.now(), c.idleMs)) setLocked(true);
      hiddenAt.current = null;
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);
  return locked ? <LockScreen onOpen={() => setLocked(false)} /> : null;
}

/** Réglages › Mon compte : activer, régler ou retirer le code de cet appareil. */
export function AppLockCard() {
  const [on, setOn] = useState(() => lock.enabled());
  const [idle, setIdle] = useState(() => lock.config()?.idleMs ?? 60_000);
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [cur, setCur] = useState("");
  const [busy, setBusy] = useState(false);
  const digits = (v: string) => v.replace(/\D/g, "").slice(0, lock.MAX_LEN);
  const activate = async () => {
    if (pin !== again) { notify("Les deux codes ne sont pas pareils."); return; }
    setBusy(true);
    try { await lock.setPin(pin, idle); setOn(true); setPin(""); setAgain(""); notify("✓ Code activé sur cet appareil"); }
    catch (e: any) { notify(e?.message || "Erreur"); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true);
    const r = await lock.check(cur);
    setBusy(false);
    setCur("");
    if (!r.ok) { notify(r.waitMs ? `Trop d'essais. Réessaie dans ${secs(r.waitMs)}.` : "Code incorrect."); return; }
    lock.clear();
    setOn(false);
    notify("✓ Code retiré");
  };
  return (
    <section className="card-box account-card">
      <h2>Code de l'appli</h2>
      <p className="hint">Facultatif. Demandé à l'ouverture d'UniC sur cet appareil : quelqu'un qui prend ton téléphone déverrouillé ne voit
        ni tes clients ni tes factures. Code oublié : tu te reconnectes avec ton mot de passe.</p>
      {!lock.supported() ? <p className="hint">Indisponible sur cet appareil.</p> : (
        <div className="form-grid">
          <label>Redemander le code
            <select value={idle} disabled={busy} onChange={(e) => { const v = Number(e.target.value); setIdle(v); lock.setIdle(v); }}>
              {lock.IDLE_CHOICES.map((c) => <option key={c.ms} value={c.ms}>{c.label}</option>)}
            </select>
          </label>
          {on ? (
            <>
              <label>Code actuel<input type="password" inputMode="numeric" autoComplete="off" value={cur} onChange={(e) => setCur(digits(e.target.value))} /></label>
              <button className="btn btn-line btn-small" type="button" disabled={busy || !lock.validPin(cur)} onClick={remove}>Retirer le code</button>
            </>
          ) : (
            <>
              <label>Nouveau code ({lock.MIN_LEN} à {lock.MAX_LEN} chiffres)<input type="password" inputMode="numeric" autoComplete="off" value={pin} onChange={(e) => setPin(digits(e.target.value))} /></label>
              <label>Le même, encore<input type="password" inputMode="numeric" autoComplete="off" value={again} onChange={(e) => setAgain(digits(e.target.value))} /></label>
              <button className="btn btn-copper btn-small" type="button" disabled={busy || !lock.validPin(pin) || !again} onClick={activate}>Activer le code</button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
