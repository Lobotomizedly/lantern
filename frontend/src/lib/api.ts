import axios, { AxiosInstance, AxiosError } from "axios";
import {
  Subject,
  Item,
  Narrative,
  Event,
  Digest,
  Artifact,
  ArtifactRequest,
  Agent,
  AgentRun,
  InvestigatorRequest,
  ReviewItem,
  ReviewAction,
  SearchQuery,
  SearchResult,
  PaginatedResponse,
  ApiError,
  DashboardStats,
  RecentActivity,
  RecentActivityResponse,
  Source,
} from "@/types";

// ============================================================================
// API Client Configuration
// ============================================================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// Request interceptor for auth
apiClient.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = typeof window !== "undefined" ? localStorage.getItem("lantern_token") : null;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    if (error.response?.status === 401) {
      // Handle unauthorized - clear token before redirect to avoid race condition
      if (typeof window !== "undefined") {
        localStorage.removeItem("lantern_token");
        localStorage.removeItem("lantern_refresh_token");
        // Use setTimeout to ensure localStorage operations complete before redirect
        setTimeout(() => {
          window.location.href = "/login";
        }, 0);
      }
    }
    return Promise.reject(error);
  }
);

// ============================================================================
// Dashboard API
// ============================================================================

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await apiClient.get<DashboardStats>("/api/v1/dashboard/stats");
  return response.data;
}

export async function getRecentActivity(limit = 20): Promise<RecentActivity[]> {
  const response = await apiClient.get<RecentActivityResponse>("/api/v1/dashboard/activity", {
    params: { limit },
  });
  return response.data.activities || [];
}

// ============================================================================
// Subjects API
// ============================================================================

export async function getSubjects(
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Subject>> {
  const response = await apiClient.get<PaginatedResponse<Subject>>("/api/v1/subjects", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

export async function getSubject(id: string): Promise<Subject> {
  const response = await apiClient.get<Subject>(`/api/v1/subjects/${id}`);
  return response.data;
}

export async function createSubject(data: Partial<Subject>): Promise<Subject> {
  // Map frontend type names to backend enum values
  const typeMap: Record<string, string> = {
    organization: "org",
    person: "person",
    topic: "topic",
    event: "topic",  // Backend doesn't have event, map to topic
    product: "topic", // Backend doesn't have product, map to topic
  };

  const subjectType = data.type || "topic";

  const payload = {
    name: data.name,
    subject_type: typeMap[subjectType] || "topic",
    description: data.description,
    config: {
      keywords: [],
      entities: [],
      sources: [],
    },
  };
  const response = await apiClient.post<Subject>("/api/v1/subjects", payload);
  return response.data;
}

export async function updateSubject(id: string, data: Partial<Subject>): Promise<Subject> {
  const response = await apiClient.patch<Subject>(`/api/v1/subjects/${id}`, data);
  return response.data;
}

export async function deleteSubject(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/subjects/${id}`);
}

/**
 * Get the digest for a specific subject.
 * Calls the backend endpoint: /api/v1/subjects/{id}/digest
 */
export async function getSubjectDigest(id: string): Promise<Digest> {
  const response = await apiClient.get<Digest>(`/api/v1/subjects/${id}/digest`);
  return response.data;
}

// ============================================================================
// Items API
// ============================================================================

export async function getItems(
  subjectId?: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Item>> {
  const response = await apiClient.get<PaginatedResponse<Item>>("/api/v1/items", {
    params: { subject_id: subjectId, page, page_size: pageSize },
  });
  return response.data;
}

export async function getItem(id: string): Promise<Item> {
  const response = await apiClient.get<Item>(`/api/v1/items/${id}`);
  return response.data;
}

export async function getItemsBySubject(
  subjectId: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Item>> {
  const response = await apiClient.get<PaginatedResponse<Item>>(
    `/api/v1/subjects/${subjectId}/items`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

// ============================================================================
// Narratives API
// ============================================================================

export async function getNarratives(
  subjectId?: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Narrative>> {
  const response = await apiClient.get<PaginatedResponse<Narrative>>("/api/v1/narratives", {
    params: { subject_id: subjectId, page, page_size: pageSize },
  });
  return response.data;
}

export async function getNarrative(id: string): Promise<Narrative> {
  const response = await apiClient.get<Narrative>(`/api/v1/narratives/${id}`);
  return response.data;
}

export async function getNarrativesBySubject(
  subjectId: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Narrative>> {
  const response = await apiClient.get<PaginatedResponse<Narrative>>(
    `/api/v1/subjects/${subjectId}/narratives`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

export async function getNarrativeItems(
  narrativeId: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Item>> {
  const response = await apiClient.get<PaginatedResponse<Item>>(
    `/api/v1/narratives/${narrativeId}/items`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

// ============================================================================
// Events API
// ============================================================================

export async function getEvents(
  subjectId?: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Event>> {
  const response = await apiClient.get<PaginatedResponse<Event>>("/api/v1/events", {
    params: { subject_id: subjectId, page, page_size: pageSize },
  });
  return response.data;
}

export async function getEvent(id: string): Promise<Event> {
  const response = await apiClient.get<Event>(`/api/v1/events/${id}`);
  return response.data;
}

export async function getEventsBySubject(
  subjectId: string,
  page = 1,
  pageSize = 50
): Promise<PaginatedResponse<Event>> {
  const response = await apiClient.get<PaginatedResponse<Event>>(
    `/api/v1/subjects/${subjectId}/events`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

// ============================================================================
// Digest API
// ============================================================================

export async function getDigests(
  subjectId: string,
  page = 1,
  pageSize = 10
): Promise<PaginatedResponse<Digest>> {
  const response = await apiClient.get<PaginatedResponse<Digest>>(
    `/api/v1/subjects/${subjectId}/digests`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

export async function getLatestDigest(subjectId: string): Promise<Digest | null> {
  const response = await apiClient.get<Digest | null>(
    `/api/v1/subjects/${subjectId}/digests/latest`
  );
  return response.data;
}

export async function generateDigest(subjectId: string): Promise<{ run_id: string }> {
  const response = await apiClient.post<{ run_id: string }>(
    `/api/v1/subjects/${subjectId}/digests/generate`
  );
  return response.data;
}

// ============================================================================
// Search API
// ============================================================================

export async function search(query: SearchQuery): Promise<SearchResult> {
  const response = await apiClient.post<SearchResult>("/api/v1/search", query);
  return response.data;
}

export async function searchSuggestions(q: string): Promise<string[]> {
  const response = await apiClient.get<string[]>("/api/v1/search/suggestions", {
    params: { q },
  });
  return response.data;
}

// ============================================================================
// Sources API
// ============================================================================

export async function getSources(page = 1, pageSize = 50): Promise<PaginatedResponse<Source>> {
  const response = await apiClient.get<PaginatedResponse<Source>>("/api/v1/sources", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

export async function getSource(id: string): Promise<Source> {
  const response = await apiClient.get<Source>(`/api/v1/sources/${id}`);
  return response.data;
}

// ============================================================================
// Artifacts API
// ============================================================================

export async function getArtifacts(
  status?: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<Artifact>> {
  const response = await apiClient.get<PaginatedResponse<Artifact>>("/api/v1/artifacts", {
    params: { status, page, page_size: pageSize },
  });
  return response.data;
}

export async function getArtifact(id: string): Promise<Artifact> {
  const response = await apiClient.get<Artifact>(`/api/v1/artifacts/${id}`);
  return response.data;
}

export async function createArtifact(request: ArtifactRequest): Promise<{ run_id: string }> {
  const response = await apiClient.post<{ run_id: string }>("/api/v1/artifacts", request);
  return response.data;
}

export async function updateArtifact(id: string, data: Partial<Artifact>): Promise<Artifact> {
  const response = await apiClient.patch<Artifact>(`/api/v1/artifacts/${id}`, data);
  return response.data;
}

export async function submitArtifactForReview(id: string): Promise<Artifact> {
  const response = await apiClient.post<Artifact>(`/api/v1/artifacts/${id}/submit`);
  return response.data;
}

// ============================================================================
// Agents API
// ============================================================================

export async function getAgents(page = 1, pageSize = 20): Promise<PaginatedResponse<Agent>> {
  const response = await apiClient.get<PaginatedResponse<Agent>>("/api/v1/agents", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

export async function getAgent(id: string): Promise<Agent> {
  const response = await apiClient.get<Agent>(`/api/v1/agents/${id}`);
  return response.data;
}

export async function createAgent(data: Partial<Agent>): Promise<Agent> {
  const response = await apiClient.post<Agent>("/api/v1/agents", data);
  return response.data;
}

export async function updateAgent(id: string, data: Partial<Agent>): Promise<Agent> {
  const response = await apiClient.patch<Agent>(`/api/v1/agents/${id}`, data);
  return response.data;
}

export async function deleteAgent(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/agents/${id}`);
}

export async function runAgent(id: string): Promise<AgentRun> {
  const response = await apiClient.post<AgentRun>(`/api/v1/agents/${id}/run`);
  return response.data;
}

export async function getAgentRuns(
  agentId: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<AgentRun>> {
  const response = await apiClient.get<PaginatedResponse<AgentRun>>(
    `/api/v1/agents/${agentId}/runs`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

export async function getAgentRun(agentId: string, runId: string): Promise<AgentRun> {
  const response = await apiClient.get<AgentRun>(`/api/v1/agents/${agentId}/runs/${runId}`);
  return response.data;
}

export async function spawnInvestigator(request: InvestigatorRequest): Promise<AgentRun> {
  const response = await apiClient.post<AgentRun>("/api/v1/agents/investigator/spawn", request);
  return response.data;
}

// ============================================================================
// Reviews API
// ============================================================================

export async function getReviewItems(
  status?: string,
  page = 1,
  pageSize = 20
): Promise<PaginatedResponse<ReviewItem>> {
  const response = await apiClient.get<PaginatedResponse<ReviewItem>>("/api/v1/reviews", {
    params: { status, page, page_size: pageSize },
  });
  return response.data;
}

export async function getReviewItem(id: string): Promise<ReviewItem> {
  const response = await apiClient.get<ReviewItem>(`/api/v1/reviews/${id}`);
  return response.data;
}

export async function submitReview(id: string, action: ReviewAction): Promise<ReviewItem> {
  const response = await apiClient.post<ReviewItem>(`/api/v1/reviews/${id}/action`, action);
  return response.data;
}

// ============================================================================
// Real-time Updates (WebSocket)
// ============================================================================

export function createWebSocketConnection(
  onMessage: (data: unknown) => void,
  onError?: (error: globalThis.Event) => void
): WebSocket | null {
  if (typeof window === "undefined") return null;

  const wsUrl = API_BASE_URL.replace(/^http/, "ws") + "/ws";
  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch {
      console.error("Failed to parse WebSocket message");
    }
  };

  ws.onerror = (error) => {
    console.error("WebSocket error:", error);
    onError?.(error);
  };

  return ws;
}

// ============================================================================
// Utility Functions
// ============================================================================

export function getApiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export { apiClient };
