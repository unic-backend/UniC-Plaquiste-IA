import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import * as I from "./Icons";

/**
 * Devis rangés dans Google Drive (faits hors de l'appli) → devis de l'appli : numéro, PDF signé, suivi, encaissement.
 * Lecture seule du Drive. Chaque ligne du PDF est vérifiée ; un PDF qui n'est pas un devis UniC est refusé.
 */
type F = { id: string; name: string; modified: string; size: number };

export function DriveDevis() {
  const [conn, setConn] = useState<boolean | null>(null);
  const [last, setLast] = useState("");
  const [files, setFiles] = useState<F[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [done, setDone] = useState<Record<string, any>>({});
  const [cid, setCid] = useState(""); const [csec, setCsec] = useState(""); const [rtok, setRtok] = useState("");
  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setMsg("");
    try { await fn(); } catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(""); }
  };
  const search = () => run("search", async () => setFiles(await api.driveQuotes(q)));
  useEffect(() => { api.driveAccount().then((r) => { setConn(r.connected); setLast(r.derniere_copie || ""); if (r.connected) search(); }, (e) => setMsg(e.message)); }, []);

  return (
    <div className="page">
      <div className="page-inner mat">
        <h1>Devis du Drive</h1>
        <p className="lede">Importe un devis rangé dans ton Google Drive : il devient un devis de l'appli (numéro, PDF signé, suivi, encaissement).</p>
        {msg && <p className="error" role="alert">{msg}</p>}
        {conn === false && (
          <section className="mat-row">
            <div className="mat-head"><b>Connecter Google Drive</b></div>
            <ol className="steps">
              <li>Google Cloud → ton projet → <b>Bibliothèque d'API</b> : active « Google Drive API ».</li>
              <li>Prends l'identifiant OAuth <b>Application Web</b> déjà créé pour la fiche Google (redirection <code>https://developers.google.com/oauthplayground</code>).</li>
              <li>OAuth Playground → roue crantée → « Use your own OAuth credentials » → portées <code>https://www.googleapis.com/auth/drive.readonly</code> et <code>https://www.googleapis.com/auth/drive.file</code> (lire les devis, et y copier ceux de l'appli) → autorise → échange le code → copie le <b>Refresh token</b>.</li>
            </ol>
            <div className="mat-fields one">
              <label>Identifiant client<input autoComplete="off" placeholder="xxxx.apps.googleusercontent.com" value={cid} onChange={(e) => setCid(e.target.value)} /></label>
              <label>Secret client<input type="password" autoComplete="off" placeholder="GOCSPX-…" value={csec} onChange={(e) => setCsec(e.target.value)} /></label>
              <label>Refresh token<input type="password" autoComplete="off" placeholder="1//…" value={rtok} onChange={(e) => setRtok(e.target.value)} /></label>
            </div>
            <button className="btn btn-copper" disabled={!!busy || !cid.trim() || !csec.trim() || !rtok.trim()}
              onClick={() => run("connect", async () => { await api.driveConnect(cid, csec, rtok); setCid(""); setCsec(""); setRtok(""); setConn(true); setFiles(await api.driveQuotes("")); })}>
              {busy === "connect" ? "Vérification…" : "Connecter le Drive"}
            </button>
            <p className="hint">Les valeurs sont testées auprès de Google, chiffrées sur ton serveur, jamais affichées.</p>
          </section>
        )}
        {conn && (
          <>
            <p className="hint">Chaque devis de l'appli est copié tout seul dans ton Drive (nom « Devis_numéro_client.pdf »).{last ? ` Dernière copie : ${last}.` : ""}</p>
            <form className="mat-row" onSubmit={(e) => { e.preventDefault(); search(); }}>
              <div className="mat-fields one">
                <label>Chercher (client, numéro)<input value={q} maxLength={120} placeholder="Ex. : Global Bridge" onChange={(e) => setQ(e.target.value)} /></label>
              </div>
              <button className="btn btn-line" disabled={!!busy}>{busy === "search" ? "Recherche…" : "Chercher dans le Drive"}</button>
            </form>
            {files.length === 0 && busy !== "search" && <p className="hint">Aucun PDF « Devis » trouvé.</p>}
            <div className="mat-list">
              {files.map((f) => (
                <section key={f.id} className="mat-row">
                  <div className="mat-head"><b>{f.name}</b><span className="hint">{f.modified.slice(0, 10)}</span></div>
                  {done[f.id] ? (
                    <p className="hint ic"><I.Check size={16} /> {done[f.id].already ? "Déjà importé" : "Importé"} : <Link to={`/devis/${done[f.id].id}`}>{done[f.id].numero}</Link>
                      {done[f.id].decision ? " · accepté (encaissement)" : ""}</p>
                  ) : (
                    <div className="row-actions">
                      <button className="btn btn-line" disabled={!!busy} onClick={() => run(f.id, async () => setDone({ ...done, [f.id]: await api.driveImport(f.id, false) }))}>Importer</button>
                      <button className="btn btn-copper" disabled={!!busy} onClick={() => run(f.id, async () => setDone({ ...done, [f.id]: await api.driveImport(f.id, true) }))}>
                        {busy === f.id ? "Import…" : "Importer · accepté"}</button>
                    </div>
                  )}
                </section>
              ))}
            </div>
            <button className="btn btn-ghost btn-small" disabled={!!busy}
              onClick={() => { if (window.confirm("Déconnecter Google Drive ? Les identifiants seront effacés du serveur.")) run("off", async () => { await api.driveDisconnect(); setConn(false); setFiles([]); }); }}>
              Déconnecter le Drive</button>
          </>
        )}
      </div>
    </div>
  );
}
