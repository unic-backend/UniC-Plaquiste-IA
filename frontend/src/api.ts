async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
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
export type Post = {
  id: string; platform: string; kind: string; title: string; body: string; hashtags: string;
  in_reply_to: string; status: string; created_at: string | null;
};
export type Mail = {
  id: string; from_addr: string; subject: string; date: string; body: string;
  summary: string; category: string; reply_draft_id: string | null;
};
export type GReview = { id: string; author: string; stars: number; comment: string; created: string; replied: boolean };
export type GProfile = { title: string; website: string; phone: string; description: string; gaps: string[]; complete: boolean };
export type MailDraft = { id: string; to_addr: string; subject: string; body: string; status: string };

export type Memo = { id: string; text: string; kind: string; source: string; pinned: boolean; created_at: string | null };

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
  deleteMemory: (id: string) => request(`/api/memory/${id}`, { method: "DELETE" }),
  mailStatus: () => request<{ read: boolean; send: boolean; ai: boolean; note: string }>("/api/mail/status"),
  mailSync: () => request<{ fetched: number; new: number }>("/api/mail/sync", { method: "POST" }),
  mails: () => request<Mail[]>("/api/mail"),
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
  deleteConversation: (id: string) =>
    request(`/api/conversations/${id}`, { method: "DELETE" }),
  chat: (body: { message: string; conversation_id?: string; file_ids?: string[]; deep?: boolean }) =>
    request<ChatOut>("/api/chat", { method: "POST", body: JSON.stringify(body) }),
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
export type Conv = { id: string; title: string; updated_at?: string };
export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  meta?: any;
  created_at?: string;
};
export type ConvDetail = { id: string; title: string; project_id?: string; messages: ChatMessage[] };
export type ChatOut = { conversation_id: string; title: string; message: ChatMessage };
export type Uploaded = { id: string; filename: string; processing: any };

export async function downloadAuth(url: string, filename: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Téléchargement impossible");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
