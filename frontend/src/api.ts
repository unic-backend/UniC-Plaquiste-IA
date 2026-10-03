const TOKEN_KEY = "unic_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    setToken(null);
    if (!path.includes("/auth/login")) window.location.href = "/login";
    throw new Error("Session expirée");
  }
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

export const api = {
  login: (email: string, password: string) =>
    request<{ token: string; user: User }>(" /api/auth/login".trim(), {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/api/auth/me"),
  conversations: (q = "") =>
    request<Conv[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  newConversation: () => request<Conv>("/api/conversations", { method: "POST" }),
  getConversation: (id: string) => request<ConvDetail>(`/api/conversations/${id}`),
  deleteConversation: (id: string) =>
    request(`/api/conversations/${id}`, { method: "DELETE" }),
  chat: (body: { message: string; conversation_id?: string; file_ids?: string[] }) =>
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

export function downloadUrl(path: string) {
  const t = getToken();
  if (!t) return path;
  return path;
}

export async function downloadAuth(url: string, filename: string) {
  const token = getToken();
  const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error("Téléchargement impossible");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
