import { Capacitor } from "@capacitor/core";
import { Filesystem, Directory } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";

const SERVER_KEY = "unic_server";
const CODE_KEY = "unic_code";

export const isNative = Capacitor.isNativePlatform();

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
}
export function clearConnection() {
  try {
    localStorage.removeItem(SERVER_KEY);
    localStorage.removeItem(CODE_KEY);
  } catch {
    /* empty */
  }
}

export class AuthError extends Error {}

/** Application native : adresse du serveur obligatoire. Web : même origine que l'API. */
export const needsServer = () => isNative && !getServer();

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
  in_reply_to: string; status: string; created_at: string | null;
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
    body: { message: string; conversation_id?: string; file_ids?: string[]; deep?: boolean },
    on: (ev: { t: "status" | "delta" | "reset"; text?: string }) => void,
  ): Promise<ChatOut & { streamed: boolean }> => {
    const headers = authHeaders(new Headers({ "Content-Type": "application/json" }));
    let res: Response | undefined;
    try { res = await fetch(apiUrl("/api/chat/stream"), { method: "POST", headers, body: JSON.stringify(body) }); } catch { /* repli ci-dessous */ }
    if (res?.status === 401) throw new AuthError("Code d'accès requis");
    if (!res || !res.ok) return { ...(await api.chat(body)), streamed: false };   // le flux n'a rien traité : on peut renvoyer sans doublon
    let streamed = false, out: (ChatOut & { streamed: boolean }) | null = null;
    const handle = (line: string) => {
      if (!line.trim()) return;
      const ev = JSON.parse(line);
      if (ev.t === "done") out = { conversation_id: ev.conversation_id, title: ev.title, message: ev.message, streamed };
      else if (ev.t === "error") throw new Error(ev.message || "Erreur");
      else { if (ev.t === "delta") streamed = true; on(ev); }
    };
    if (res.body && typeof res.body.getReader === "function") {
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) { handle(buf.slice(0, nl)); buf = buf.slice(nl + 1); }
      }
      handle(buf);
    } else {
      (await res.text()).split("\n").forEach(handle);   // pas de lecture en flux : tout arrive d'un coup
    }
    if (!out) throw new Error("Réponse interrompue. Réessaie.");
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
  saveSettings: (body: any) =>
    request("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  health: () => request<any>("/api/health"),
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
  fresh?: boolean;
};
export type ConvDetail = { id: string; title: string; project_id?: string; messages: ChatMessage[] };
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
