import { Capacitor } from "@capacitor/core";
import { Filesystem, Directory } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";

const SERVER_KEY = "unic_server";
const CODE_KEY = "unic_code";

export const isNative = Capacitor.isNativePlatform();
/** Application PC (Electron) : l'interface est embarquée, l'API est sur le serveur UniC. */
type DesktopBridge = { desktop: true; configureWorker?: (server: string, code: string) => void };
const desktopBridge = (): DesktopBridge | undefined => (typeof window !== "undefined" ? (window as { unicDesktop?: DesktopBridge }).unicDesktop : undefined);
export const isDesktop = !!desktopBridge();

/** Appli PC : transmet le serveur et le code au moteur local (Ollama) pour qu'il réponde quand Claude est indisponible. */
export function syncDesktopWorker() {
  try { if (getServer() && getCode()) desktopBridge()?.configureWorker?.(getServer(), getCode()); } catch { /* sans effet hors PC */ }
}
/** Application installée (téléphone ou PC) : adresse du serveur à saisir. */
export const hasServerField = isNative || isDesktop;

function store(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export const getServer = () => store(SERVER_KEY).replace(/\/+$/, "");
export const getCode = () => store(CODE_KEY);
export function saveConnection(server: string, code: string) {
  try {
    localStorage.setItem(SERVER_KEY, server.trim().replace(/\/+$/, ""));
    localStorage.setItem(CODE_KEY, code);
  } catch {
    /* stockage indisponible */
  }
  syncDesktopWorker();
}
export function clearConnection() {
  try {
    localStorage.removeItem(SERVER_KEY);
    localStorage.removeItem(CODE_KEY);
  } catch {
    /* empty */
  }
}

/** Ton serveur : proposé d'office à la connexion (modifiable si un jour il change). */
export const DEFAULT_SERVER = "https://unic-plaquiste-ia.onrender.com";
const EMAIL_KEY = "unic_email";
export const getSavedEmail = () => store(EMAIL_KEY);

const deviceLabel = () => (isNative ? "Téléphone" : isDesktop ? "PC (appli)" : "Navigateur");

/** État du compte sur un serveur donné (avant connexion) : e-mail + mot de passe déjà choisis ? */
export async function authStatus(server: string): Promise<{ account: boolean; code_required: boolean }> {
  const res = await fetch(`${server.replace(/\/+$/, "")}/api/auth/status`);
  if (!res.ok) throw new Error("Serveur injoignable : vérifie l'adresse et ta connexion.");
  return res.json();
}

/** Connexion e-mail + mot de passe : le jeton remplace le code d'accès dans l'appli (même emplacement, même en-tête). */
export async function loginWithPassword(server: string, email: string, password: string) {
  const base = server.replace(/\/+$/, "");
  const res = await fetch(`${base}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim(), password, device: deviceLabel() }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new AuthError(data.detail || "Connexion impossible");
  saveConnection(base, data.token);
  try { localStorage.setItem(EMAIL_KEY, email.trim()); } catch { /* ignoré */ }
}

/** Choisir / changer son e-mail et mot de passe (avec le code d'accès : mot de passe oublié ou première fois). */
export async function setAccount(email: string, password: string, currentPassword = "") {
  const r = await request<{ token: string }>("/api/auth/account", { method: "PUT",
    body: JSON.stringify({ email: email.trim(), password, current_password: currentPassword }) });
  saveConnection(getServer(), r.token);
  try { localStorage.setItem(EMAIL_KEY, email.trim()); } catch { /* ignoré */ }
}

/** Déconnexion : le serveur oublie cet appareil ; l'adresse du serveur et l'e-mail restent proposés. */
export async function signOut() {
  try { await fetch(apiUrl("/api/auth/logout"), { method: "POST", headers: authHeaders() }); } catch { /* hors ligne : on oublie quand même */ }
  try { localStorage.removeItem(CODE_KEY); } catch { /* ignoré */ }
}

export class AuthError extends Error {}
/** Connexion coupée pendant la réponse (appli quittée, réseau perdu) : le serveur, lui, continue le travail. */
export class Interrupted extends Error {
  constructor(public conversationId?: string) {
    super("Connexion coupée. Si UniC a reçu ta demande, il la termine sur le serveur : elle apparaîtra dans le menu des conversations.");
  }
}

/** Application native : adresse du serveur obligatoire. Web : même origine que l'API. */
export const needsServer = () => hasServerField && !getServer();

export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : getServer() + path;
}

function authHeaders(headers = new Headers()): Headers {
  const code = getCode();
  if (code) headers.set("X-Access-Code", code);
  return headers;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = authHeaders(new Headers(init.headers));
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response | undefined;
  // lecture seule : on réessaie 2 fois (serveur qui redémarre après une mise à jour) ; jamais un envoi, pour éviter les doublons
  const tries = (init.method || "GET").toUpperCase() === "GET" ? 3 : 1;
  for (let i = 0; i < tries && !res; i++) {
    try {
      res = await fetch(apiUrl(path), { ...init, headers });
    } catch {
      if (i < tries - 1) await new Promise((r) => setTimeout(r, 2500));
    }
  }
  if (!res) {
    throw new Error(
      "Serveur injoignable. Il redémarre peut-être après une mise à jour (1 à 2 min) : réessayez. Sinon vérifiez votre connexion.",
    );
  }
  if (res.status === 401) throw new AuthError("Code d'accès requis");
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {
      /* empty */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res as unknown as T;
}

export type Platform = {
  id: string; label: string; description: string; tip: string; max_chars: number;
  linked: boolean; handle: string; page_url: string; auto_publish: boolean;
};
export type GPlan = {
  cadence_days: number; last_published_at: string | null; days_since: number | null; due: boolean; next_due_at: string;
  published_last_30_days: number; target_last_30_days: number; theme: { id: string; label: string };
  draft: { id: string; title: string; body: string; photo_brief: string; status: string } | null;
  checklist: { items: { id: string; label: string; done: boolean }[]; done: number; total: number };
  keywords: Record<"metier" | "zones" | "recherches" | "categories", string[]>;
  api_configured: boolean; ai: boolean; auto_publish_note: string;
};
export type GOptimize = {
  description: string; services?: { nom: string; texte: string }[]; questions?: { q: string; r: string }[]; categories?: string[];
};
export type Post = {
  photo_brief?: string;
  id: string; platform: string; kind: string; title: string; body: string; hashtags: string;
  in_reply_to: string; status: string; created_at: string | null; external_url?: string; external_id?: string;
};
export type LinkedInStatus = {
  app_saved: boolean; client_id: string; connected: boolean; name: string; days_left: number | null;
  page_id: string; page_scope: boolean; redirect_uri: string;
};
export type InstagramStatus = {
  app_saved: boolean; app_id: string; connected: boolean; username: string; days_left: number | null; redirect_uri: string;
};
export type Mail = {
  suspect?: boolean;
  id: string; from_addr: string; subject: string; date: string; body: string;
  summary: string; category: string; reply_draft_id: string | null;
};
export type GReview = { id: string; author: string; stars: number; comment: string; created: string; replied: boolean };
export type GProfile = { title: string; website: string; phone: string; description: string; gaps: string[]; complete: boolean };
export type MailDraft = { id: string; to_addr: string; subject: string; body: string; status: string };

export type Memo = {
  id: string; text: string; kind: string; source: string; pinned: boolean; created_at: string | null;
  nature?: string; state?: string; importance?: number; occurrences?: number; expires_at?: string | null;
};
export type MemState = {
  actifs: number; a_confirmer: number; rejetes: number; archives: number; taches: number; conflits: number;
  avertissement: string | null; recherche: string; portee_conflits: string;
};
export type MemConflict = { a: { id: string; text: string }; b: { id: string; text: string }; raison: string };
export type Usage = {
  aujourdhui_usd: number; semaine_usd: number; mois_usd: number; total_usd: number; moyenne_par_message_usd: number;
  messages_aujourdhui: number; messages_mois: number; messages_total: number;
  par_modele: { model: string; messages: number; cout_usd: number }[]; jours: { jour: string; cout_usd: number }[];
  credit_usd: number | null; reste_usd: number | null; messages_restants_estimes: number | null; tarif_inconnu: boolean; avertissement: string;
};
export type JournalRow = { id: string; at: string | null; action: string; label: string; target: string; details: string };

const json = (b: unknown) => ({ body: JSON.stringify(b) });

export const net = {
  platforms: () =>
    request<{ platforms: Platform[]; auto_publish_note: string; ai_available: boolean }>("/api/reseaux/platforms"),
  setAccount: (id: string, b: { handle: string; page_url: string; linked: boolean }) =>
    request(`/api/reseaux/accounts/${id}`, { method: "PUT", ...json(b) }),
  posts: () => request<Post[]>("/api/reseaux/posts"),
  createPost: (b: Partial<Post>) => request<Post>("/api/reseaux/posts", { method: "POST", ...json(b) }),
  advance: (id: string) => request<Post>(`/api/reseaux/posts/${id}/advance`, { method: "POST" }),
  deletePost: (id: string) => request(`/api/reseaux/posts/${id}`, { method: "DELETE" }),
  tiktokScript: (topic: string, details: string) =>
    request<Post>("/api/tiktok/script", { method: "POST", body: JSON.stringify({ topic, details }) }),
  whatsappMessage: (kind: string, customer_id: string, phone: string, details: string) =>
    request<Post>("/api/whatsapp/message", { method: "POST", body: JSON.stringify({ kind, customer_id, phone, details }) }),
  siteStatus: () => request<{ connected: boolean; repo: string; branch: string; site_url: string }>("/api/website"),
  siteConnect: (token: string) => request("/api/website/connect", { method: "PUT", body: JSON.stringify({ token }) }),
  siteDisconnect: () => request("/api/website", { method: "DELETE" }),
  siteDraft: (topic: string, details: string) =>
    request<{ id: string; title: string }>("/api/website/draft", { method: "POST", body: JSON.stringify({ topic, details }) }),
  sitePreview: (id: string) => request<{ html: string; words: number; url: string }>(`/api/website/preview/${id}`),
  sitePublish: (id: string) => request<{ url: string; commit: string }>(`/api/website/publish/${id}`, { method: "POST" }),
  instagramStatus: () => request<InstagramStatus>("/api/instagram"),
  instagramSaveApp: (app_id: string, app_secret: string) =>
    request<InstagramStatus>("/api/instagram/app", { method: "PUT", body: JSON.stringify({ app_id, app_secret }) }),
  instagramAuthUrl: () => request<{ url: string }>("/api/instagram/auth-url"),
  instagramDisconnect: () => request("/api/instagram", { method: "DELETE" }),
  instagramPublish: (id: string, photo: File) => {
    const fd = new FormData();
    fd.append("photo", photo, photo.name);
    return request<Post>(`/api/reseaux/posts/${id}/publish-instagram`, { method: "POST", body: fd });
  },
  linkedinStatus: () => request<LinkedInStatus>("/api/linkedin"),
  linkedinSaveApp: (client_id: string, client_secret: string, page_id: string) =>
    request<LinkedInStatus>("/api/linkedin/app", { method: "PUT", body: JSON.stringify({ client_id, client_secret, page_id }) }),
  linkedinAuthUrl: (page: boolean) => request<{ url: string }>(`/api/linkedin/auth-url?page=${page}`),
  linkedinDisconnect: () => request("/api/linkedin", { method: "DELETE" }),
  linkedinPublish: (id: string, target: "profile" | "page", photo: File | null) => {
    const fd = new FormData();
    fd.append("target", target);
    if (photo) fd.append("photo", photo, photo.name);
    return request<Post>(`/api/reseaux/posts/${id}/publish-linkedin`, { method: "POST", body: fd });
  },
  generate: (b: { platform: string; topic?: string; details?: string; comment?: string }) =>
    request<{ text: string; warning: string | null }>("/api/reseaux/generate", { method: "POST", ...json(b) }),
  boost: (b: { target: string; facts?: string }) =>
    request<{ plan: string; note: string }>("/api/reseaux/boost", { method: "POST", ...json(b) }),
  publish: (id: string) => request<Post>(`/api/reseaux/posts/${id}/publish`, { method: "POST" }),
  gStatus: () => request<{ configured: boolean; missing: string[]; ai: boolean }>("/api/google/status"),
  gProfile: () => request<GProfile>("/api/google/profile"),
  gReviews: () => request<GReview[]>("/api/google/reviews"),
  gReplyDraft: (id: string, b: { comment: string; stars: number }) =>
    request<Post>(`/api/google/reviews/${encodeURIComponent(id)}/reply-draft`, { method: "POST", ...json(b) }),
  memories: () => request<Memo[]>("/api/memory"),
  addMemory: (b: { text: string; kind: string; pinned: boolean }) =>
    request<Memo>("/api/memory", { method: "POST", ...json(b) }),
  discardDoc: (kind: string, id: string) => request(`/api/documents/${kind}/${id}`, { method: "DELETE" }),
  gPlan: () => request<GPlan>("/api/google/plan"),
  gPlanDraft: (topic: string) => request<Post>("/api/google/plan/draft", { method: "POST", ...json({ topic }) }),
  gPlanDone: (id: string) => request<{ plan: GPlan }>(`/api/google/plan/${id}/done`, { method: "POST", ...json({}) }),
  gCheck: (id: string, done: boolean) =>
    request<GPlan["checklist"]>(`/api/google/plan/checklist/${id}`, { method: "PUT", ...json({ done }) }),
  gOptimize: () => request<GOptimize>("/api/google/optimize", { method: "POST" }),
  editPost: (id: string, body: string) => request<Post>(`/api/reseaux/posts/${id}`, { method: "PATCH", ...json({ body }) }),
  memoriesBy: (state: string) => request<Memo[]>(`/api/memory?state=${state}`),
  memState: () => request<MemState>("/api/memory/state"),
  memConflicts: () => request<MemConflict[]>("/api/memory/conflicts"),
  decideMemory: (id: string, action: string) =>
    request<Memo>(`/api/memory/${id}`, { method: "PATCH", ...json({ action }) }),
  importMemory: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ candidats: number }>("/api/memory/import", { method: "POST", body: fd });
  },
  usage: () => request<Usage>("/api/usage"),
  voiceStatus: () => request<{ configured: boolean; voice_id: string; limits: string }>("/api/voice"),
  voiceConnect: (key: string) => request("/api/voice/connect", { method: "POST", body: JSON.stringify({ key }) }),
  voiceDisconnect: () => request("/api/voice/connect", { method: "DELETE" }),
  voiceList: () => request<{ id: string; name: string; category: string; gender: string; accent: string; mine: boolean; preview: string }[]>("/api/voice/voices"),
  voiceSelect: (voice_id: string) => request("/api/voice/select", { method: "POST", body: JSON.stringify({ voice_id }) }),
  voiceDelete: (id: string) => request(`/api/voice/voices/${id}`, { method: "DELETE" }),
  voiceClone: (name: string, file: Blob, filename: string) => {
    const fd = new FormData();
    fd.append("name", name); fd.append("own_voice", "true"); fd.append("file", file, filename);
    return request<{ id: string; name: string }>("/api/voice/clone", { method: "POST", body: fd });
  },
  setBudget: (amount_usd: number) => request<Usage>("/api/usage/budget", { method: "PUT", ...json({ amount_usd }) }),
  journal: (action = "") => request<JournalRow[]>(`/api/journal${action ? `?action=${encodeURIComponent(action)}` : ""}`),
  deleteMemory: (id: string) => request(`/api/memory/${id}`, { method: "DELETE" }),
  mailStatus: () => request<{ read: boolean; send: boolean; ai: boolean; note: string }>("/api/mail/status"),
  mailAccount: () => request<{ connected: boolean; address: string; env_override: boolean }>("/api/mail/account"),
  connectGmail: (address: string, password: string) =>
    request<{ connected: boolean; address: string }>("/api/mail/account", { method: "PUT", ...json({ address, password }) }),
  disconnectGmail: () => request<{ connected: boolean }>("/api/mail/account", { method: "DELETE" }),
  mailSync: () => request<{ fetched: number; new: number }>("/api/mail/sync", { method: "POST" }),
  mails: () => request<Mail[]>("/api/mail"),
  mailPurge: () => request<{ purged: number }>("/api/mail/purge", { method: "POST" }),
  analyze: (id: string) => request<Mail & { priority: string; action: string }>(`/api/mail/${id}/analyze`, { method: "POST" }),
  replyDraft: (id: string, instruction: string) =>
    request<MailDraft>(`/api/mail/${id}/reply-draft`, { method: "POST", ...json({ instruction }) }),
  editDraft: (id: string, b: Partial<MailDraft>) =>
    request<MailDraft>(`/api/mail/drafts/${id}`, { method: "PATCH", ...json(b) }),
  approveDraft: (id: string) => request(`/api/mail/drafts/${id}/approve`, { method: "POST" }),
  sendDraft: (id: string) => request(`/api/mail/drafts/${id}/send`, { method: "POST" }),
};

export const api = {
  me: () => request<User>("/api/auth/me"),
  conversations: (q = "") =>
    request<Conv[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  newConversation: () => request<Conv>("/api/conversations", { method: "POST" }),
  getConversation: (id: string) => request<ConvDetail>(`/api/conversations/${id}`),
  patchConversation: (id: string, b: { title?: string; pinned?: boolean }) =>
    request<Conv>(`/api/conversations/${id}`, { method: "PATCH", ...json(b) }),
  deleteConversation: (id: string) =>
    request(`/api/conversations/${id}`, { method: "DELETE" }),
  chat: (body: { message: string; conversation_id?: string; file_ids?: string[]; deep?: boolean }) =>
    request<ChatOut>("/api/chat", { method: "POST", body: JSON.stringify(body) }),
  /** Réponse en flux : statut + texte au fil de l'eau. Si le flux ne démarre pas, repli sur la réponse d'un bloc. */
  chatStream: async (
    body: { message: string; conversation_id?: string; file_ids?: string[]; deep?: boolean; voice?: boolean },
    on: (ev: { t: "status" | "delta" | "reset" | "conv"; text?: string; conversation_id?: string }) => void,
  ): Promise<ChatOut & { streamed: boolean }> => {
    const headers = authHeaders(new Headers({ "Content-Type": "application/json" }));
    let res: Response | undefined;
    try { res = await fetch(apiUrl("/api/chat/stream"), { method: "POST", headers, body: JSON.stringify(body) }); }
    catch { throw new Interrupted(body.conversation_id); }   // la demande a pu partir : jamais de second envoi (doublon)
    if (res?.status === 401) throw new AuthError("Code d'accès requis");
    if (!res || !res.ok) return { ...(await api.chat(body)), streamed: false };   // le flux n'a rien traité : on peut renvoyer sans doublon
    let streamed = false, out: (ChatOut & { streamed: boolean }) | null = null, convId: string | undefined = body.conversation_id;
    const handle = (line: string) => {
      if (!line.trim()) return;
      const ev = JSON.parse(line);
      if (ev.t === "done") out = { conversation_id: ev.conversation_id, title: ev.title, message: ev.message, streamed };
      else if (ev.t === "error") throw new Error(ev.message || "Erreur");
      else { if (ev.t === "delta") streamed = true; if (ev.t === "conv") convId = ev.conversation_id; on(ev); }
    };
    if (res.body && typeof res.body.getReader === "function") {
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try { chunk = await reader.read(); } catch { throw new Interrupted(convId); }
        const { done, value } = chunk;
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) { handle(buf.slice(0, nl)); buf = buf.slice(nl + 1); }
      }
      handle(buf);
    } else {
      (await res.text()).split("\n").forEach(handle);   // pas de lecture en flux : tout arrive d'un coup
    }
    if (!out) throw new Interrupted(convId);
    return out;
  },
  upload: async (file: File, projectId?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (projectId) fd.append("project_id", projectId);
    return request<Uploaded>("/api/files", { method: "POST", body: fd });
  },
  customers: (q = "") => request<any[]>(`/api/customers${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  createCustomer: (body: any) =>
    request("/api/customers", { method: "POST", body: JSON.stringify(body) }),
  updateCustomer: (id: string, body: any) =>
    request(`/api/customers/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  suppliers: () => request<any[]>("/api/suppliers"),
  createSupplier: (body: any) =>
    request("/api/suppliers", { method: "POST", body: JSON.stringify(body) }),
  materials: () => request<any[]>("/api/materials"),
  addPrice: (id: string, body: any) =>
    request(`/api/materials/${id}/prices`, { method: "POST", body: JSON.stringify(body) }),
  services: () => request<any[]>("/api/services"),
  projects: () => request<any[]>("/api/projects"),
  getProject: (id: string) => request<any>(`/api/projects/${id}`),
  createProject: (body: any) =>
    request("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  quotes: () => request<any[]>("/api/quotes"),
  getQuote: (id: string) => request<any>(`/api/quotes/${id}`),
  preview: (artifactId: string) => request<{ pages: number; images: string[]; filename: string }>(`/api/artifacts/${artifactId}/preview`),
  validateMessage: (id: string, on: boolean) => request<{ validated: boolean; total: number }>(`/api/messages/${id}/validate`, { method: on ? "POST" : "DELETE" }),
  regenerateCoverLetter: (id: string) => request<{ cover_letter: string }>(`/api/quotes/${id}/cover-letter`, { method: "POST" }),
  saveCoverLetter: (id: string, text: string) => request<{ cover_letter: string }>(`/api/quotes/${id}/cover-letter`, { method: "PUT", body: JSON.stringify({ text }) }),
  approveQuote: (id: string) => request(`/api/quotes/${id}/approve`, { method: "POST" }),
  invoices: () => request<any[]>("/api/invoices"),
  getInvoice: (id: string) => request<any>(`/api/invoices/${id}`),
  payInvoice: (id: string, body: any) =>
    request(`/api/invoices/${id}/payments`, { method: "POST", body: JSON.stringify(body) }),
  pos: () => request<any[]>("/api/purchase-orders"),
  getPo: (id: string) => request<any>(`/api/purchase-orders/${id}`),
  dns: () => request<any[]>("/api/delivery-notes"),
  getDn: (id: string) => request<any>(`/api/delivery-notes/${id}`),
  settings: () => request<any>("/api/settings"),
  backups: () => request<any>("/api/backups"),
  devices: () => request<{ devices: { device: string; last_used: string }[]; account: boolean; email: string }>("/api/auth/devices"),
  unpaid: () => request<any>("/api/invoices-unpaid"),
  leads: () => request<any[]>("/api/leads"),
  updateLead: (id: string, status: string) => request<any>(`/api/leads/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  agenda: (days = 60) => request<any>(`/api/agenda?days=${days}`),
  addAppointment: (body: any) => request<any>("/api/agenda", { method: "POST", body: JSON.stringify(body) }),
  updateAppointment: (id: string, body: any) => request<any>(`/api/agenda/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  backupNow: () => request<any>("/api/backups", { method: "POST" }),
  restoreBackup: (file: File) => { const fd = new FormData(); fd.append("file", file); return request<any>("/api/backups/restore", { method: "POST", body: fd }); },
  uploadSignature: (file: File) => { const fd = new FormData(); fd.append("file", file); return request<{ ok: boolean }>("/api/settings/signature", { method: "PUT", body: fd }); },
  deleteSignature: () => request<{ ok: boolean }>("/api/settings/signature", { method: "DELETE" }),
  uploadStamp: (file: File) => { const fd = new FormData(); fd.append("file", file); return request<{ ok: boolean }>("/api/settings/stamp", { method: "PUT", body: fd }); },
  deleteStamp: () => request<{ ok: boolean }>("/api/settings/stamp", { method: "DELETE" }),
  saveSettings: (body: any) =>
    request("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  health: () => request<any>("/api/health"),
  connectors: () => request<Record<string, boolean>>("/api/connectors"),
  selfcare: () => request<any>("/api/selfcare"),
  checkin: (b: any) => request<any>("/api/checkins", { method: "POST", body: JSON.stringify(b) }),
  checkins: () => request<any[]>("/api/checkins"),
  checkinSummary: () => request<any>("/api/checkins/summary"),
  signQuote: (id: string, b: any) => request<any>(`/api/quotes/${id}/signature`, { method: "POST", body: JSON.stringify(b) }),
  quoteSignatures: (id: string) => request<any[]>(`/api/quotes/${id}/signature`),
  setAutoWork: (enabled: boolean) => request<any>("/api/selfcare/auto", { method: "POST", body: JSON.stringify({ enabled }) }),
  selfCheck: () => request<any>("/api/selfcare/check", { method: "POST" }),
  incident: (id: string) => request<any>(`/api/selfcare/incidents/${id}`),
  setIncident: (id: string, status: string) => request<any>(`/api/selfcare/incidents/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  repair: (body: { kind: "fix" | "feature"; request?: string; incident_id?: string }) =>
    request<any>("/api/selfcare/repair", { method: "POST", body: JSON.stringify(body) }),
  repairJob: (id: string) => request<any>(`/api/selfcare/jobs/${id}`),
  mergeJob: (id: string) => request<any>(`/api/selfcare/jobs/${id}/merge`, { method: "POST" }),
  closeJob: (id: string) => request<any>(`/api/selfcare/jobs/${id}/close`, { method: "POST" }),
  githubConnect: (body: { token?: string; repo?: string; base?: string; deploy_hook?: string }) =>
    request<any>("/api/selfcare/github", { method: "PUT", body: JSON.stringify(body) }),
  githubDisconnect: () => request<any>("/api/selfcare/github", { method: "DELETE" }),
  createAgent: (body: { name: string; mission: string; every_hours: number }) =>
    request<any>("/api/agents", { method: "POST", body: JSON.stringify(body) }),
  setAgent: (id: string, status: string) => request<any>(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  runAgent: (id: string) => request<any>(`/api/agents/${id}/run`, { method: "POST" }),
  deleteAgent: (id: string) => request<any>(`/api/agents/${id}`, { method: "DELETE" }),
  knowledge: () => request<any[]>("/api/knowledge"),
  search: (q: string) => request<any>(`/api/search?q=${encodeURIComponent(q)}`),
  emails: () => request<any[]>("/api/emails"),
  files: () => request<any[]>("/api/files"),
};

export type User = { id: string; email: string; name: string; role: string };
export type Conv = { id: string; title: string; updated_at?: string; pinned?: boolean };
export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  meta?: any;
  created_at?: string;
  validated?: boolean;
  files?: { name: string; mime?: string; id?: string; file?: File }[];
  fresh?: boolean;
};
export type ConvDetail = { id: string; title: string; project_id?: string; messages: ChatMessage[]; working?: boolean };
export type ChatOut = { conversation_id: string; title: string; message: ChatMessage };
export type Uploaded = { id: string; filename: string; processing: any };

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(new Error("Lecture du fichier impossible"));
    reader.readAsDataURL(blob);
  });
}

/** Partage direct du PDF (WhatsApp, e-mail…) : feuille de partage Android, avec un texte facultatif (lettre d'accompagnement). */
/** Partage d'un texte (relance…) par la feuille de partage du téléphone : WhatsApp, SMS, e-mail… */
export async function shareText(text: string, title = "Message") {
  if (isNative) { await Share.share({ title, text, dialogTitle: "Envoyer" }); return; }
  const nav = navigator as Navigator & { share?: (d: ShareData) => Promise<void> };
  if (nav.share) { await nav.share({ title, text }); return; }
  await navigator.clipboard.writeText(text);
}

export async function shareDocument(url: string, filename: string, text = "") {
  const res = await fetch(apiUrl(url), { headers: authHeaders() });
  if (res.status === 401) throw new AuthError("Code d'accès requis");
  if (!res.ok) throw new Error("Partage impossible : le PDF est introuvable.");
  const blob = await res.blob();
  const safe = filename.replace(/[^\w.\-]+/g, "_");
  if (isNative) {
    const written = await Filesystem.writeFile({ path: safe, data: await blobToBase64(blob), directory: Directory.Cache });
    await Share.share({ title: filename, text: text || undefined, url: written.uri, dialogTitle: "Envoyer le document" });
    return;
  }
  const file = new File([blob], safe, { type: blob.type || "application/pdf" });
  const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean };
  if (nav.canShare?.({ files: [file] })) { await nav.share({ files: [file], title: filename, text }); return; }
  await downloadAuth(url, filename);
}

/** Fichier du serveur (avec le code d'accès) sous forme d'adresse locale affichable dans <img>. */
export async function fetchBlobUrl(url: string): Promise<string> {
  const res = await fetch(apiUrl(url), { headers: authHeaders() });
  if (res.status === 401) throw new AuthError("Code d'accès requis");
  if (!res.ok) throw new Error("Image introuvable");
  return URL.createObjectURL(await res.blob());
}

export async function downloadAuth(url: string, filename: string) {
  const res = await fetch(apiUrl(url), { headers: authHeaders() });
  if (res.status === 401) throw new AuthError("Code d'accès requis");
  if (!res.ok) throw new Error("Téléchargement impossible");
  const blob = await res.blob();
  if (isNative) {
    // WebView : pas de téléchargement par lien → fichier en cache + feuille de partage Android
    const safe = filename.replace(/[^\w.\-]+/g, "_");
    const written = await Filesystem.writeFile({ path: safe, data: await blobToBase64(blob), directory: Directory.Cache });
    await Share.share({ title: filename, url: written.uri, dialogTitle: "Ouvrir ou enregistrer" });
    return;
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
