/**
 * Memline TypeScript client. Zero runtime dependencies (fetch only).
 *
 *   import { Memline } from "memline";
 *
 *   const ml = new Memline({ apiKey: "ml_...", baseUrl: "https://mindcarry.fly.dev" });
 *   const out = await ml.remember({ text: "I live in Austin.", userId: "user-42" });
 *   const hits = await ml.search({ query: "where does the user live?", userId: "user-42" });
 *
 * Every stored memory carries evidence, a grounding verdict and a
 * validity window. Writes pass the grounding gate: ungrounded extracted
 * candidates come back in the response's `rejected` list with a reason
 * instead of being stored. See API.md for the full contract.
 */

export interface Scope {
  userId?: string;
  agentId?: string;
  appId?: string;
  runId?: string;
}

export interface RememberOptions extends Scope {
  text?: string;
  messages?: Array<Record<string, unknown>>;
  infer?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SearchOptions extends Scope {
  query: string;
  limit?: number;
  asOf?: string;
  threshold?: number;
}

export interface AssembleOptions extends Scope {
  query: string;
  maxTokens?: number;
}

export class MemlineError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`Memline API error ${status}: ${body.slice(0, 300)}`);
    this.status = status;
    this.body = body;
  }
}

interface ClientOptions {
  apiKey: string;
  baseUrl?: string;
}

export class Memline {
  private apiKey: string;
  private baseUrl: string;

  constructor(options: ClientOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? "https://mindcarry.fly.dev").replace(/\/$/, "");
  }

  private async call(method: string, path: string,
                     payload?: Record<string, unknown>,
                     params?: Record<string, string | number>): Promise<any> {
    let url = this.baseUrl + path;
    const clean = Object.entries(params ?? {}).filter(([, v]) => v !== "" && v !== undefined);
    if (clean.length) {
      url += "?" + new URLSearchParams(clean.map(([k, v]) => [k, String(v)])).toString();
    }
    const resp = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
      body: payload !== undefined ? JSON.stringify(payload) : undefined,
    });
    const text = await resp.text();
    if (!resp.ok) throw new MemlineError(resp.status, text);
    return text ? JSON.parse(text) : {};
  }

  private scope(o: Scope): Record<string, unknown> {
    const out: Record<string, unknown> = {
      user_id: o.userId ?? "",
      agent_id: o.agentId ?? "",
      app_id: o.appId ?? "",
    };
    if (o.runId) out.run_id = o.runId;
    return out;
  }

  /** Store through the write gate. Response separates results,
   *  rejected (ungrounded) and skipped_duplicates. */
  async remember(options: RememberOptions): Promise<any> {
    const payload: Record<string, unknown> = {
      ...this.scope(options),
      infer: options.infer ?? true,
      metadata: options.metadata ?? {},
    };
    if (options.text !== undefined) payload.text = options.text;
    if (options.messages !== undefined) payload.messages = options.messages;
    return this.call("POST", "/v1/remember", payload);
  }

  /** POST /v1/memories; identical semantics to remember(). */
  async add(options: RememberOptions): Promise<any> {
    const payload: Record<string, unknown> = {
      ...this.scope(options),
      infer: options.infer ?? true,
      metadata: options.metadata ?? {},
    };
    if (options.text !== undefined) payload.text = options.text;
    if (options.messages !== undefined) payload.messages = options.messages;
    return this.call("POST", "/v1/memories", payload);
  }

  /** Hybrid search over currently valid memories; results carry
   *  evidence, score components and a plain-language why array.
   *  Pass asOf (ISO timestamp) to search the past. */
  async search(options: SearchOptions): Promise<any> {
    const payload: Record<string, unknown> = {
      ...this.scope(options),
      query: options.query,
      limit: options.limit ?? 10,
      threshold: options.threshold ?? 0,
    };
    if (options.asOf) payload.as_of = options.asOf;
    return this.call("POST", "/v1/memories/search", payload);
  }

  async get(memoryId: number): Promise<any> {
    return this.call("GET", `/v1/memories/${memoryId}`);
  }

  async list(options: Scope & { limit?: number; offset?: number } = {}): Promise<any> {
    return this.call("GET", "/v1/memories", undefined, {
      user_id: options.userId ?? "",
      agent_id: options.agentId ?? "",
      app_id: options.appId ?? "",
      limit: options.limit ?? 100,
      offset: options.offset ?? 0,
    });
  }

  async update(memoryId: number, text: string,
               metadata?: Record<string, unknown>): Promise<any> {
    return this.call("PUT", `/v1/memories/${memoryId}`, { text, metadata });
  }

  async delete(memoryId: number): Promise<any> {
    return this.call("DELETE", `/v1/memories/${memoryId}`);
  }

  async deleteAll(options: Scope = {}): Promise<any> {
    return this.call("DELETE", "/v1/memories", undefined, {
      user_id: options.userId ?? "",
      agent_id: options.agentId ?? "",
      app_id: options.appId ?? "",
      run_id: options.runId ?? "",
    });
  }

  /** Full event history, kept even after the memory is gone. */
  async history(memoryId: number): Promise<any> {
    return this.call("GET", `/v1/memories/${memoryId}/history`);
  }

  /** Close the validity window now: stops being asserted about the
   *  present, without being deleted. */
  async invalidate(memoryId: number): Promise<any> {
    return this.call("POST", `/v1/memories/${memoryId}/invalidate`, {});
  }

  /** The typed understanding profile, including open unknowns. */
  async understanding(userId = ""): Promise<any> {
    return this.call("GET", "/v1/understanding", undefined, { user_id: userId });
  }

  /** Token-budgeted context for one prompt, with supporting
   *  understandings, omissions with reasons, and unknowns. */
  async assembleContext(options: AssembleOptions): Promise<any> {
    return this.call("POST", "/v1/assemble_context", {
      ...this.scope(options),
      query: options.query,
      max_tokens: options.maxTokens ?? 1500,
    });
  }

  /** Grounded percentage, contradictions, stale count, gate pass
   *  rate, coverage: the store reports on itself. */
  async memoryHealth(userId = ""): Promise<any> {
    return this.call("GET", "/v1/memory_health", undefined, { user_id: userId });
  }

  /** What the write gate refused to store, with reasons. */
  async rejections(userId = "", limit = 20): Promise<any> {
    return this.call("GET", "/v1/rejections", undefined, { user_id: userId, limit });
  }

  async graph(userId = ""): Promise<any> {
    return this.call("GET", "/v1/graph", undefined, { user_id: userId });
  }
}
