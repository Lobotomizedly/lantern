// ============================================================================
// Core Enums
// ============================================================================

export type Sentiment = "positive" | "neutral" | "negative" | "mixed";

export type LifecycleStage =
  | "emerging"
  | "growing"
  | "peak"
  | "declining"
  | "dormant";

export type ItemType =
  | "article"
  | "social_post"
  | "video"
  | "podcast"
  | "document"
  | "press_release"
  | "filing"
  | "research"
  | "other";

export type SourceType =
  | "news"
  | "social"
  | "blog"
  | "forum"
  | "official"
  | "academic"
  | "other";

export type EventType =
  | "publication"
  | "statement"
  | "action"
  | "announcement"
  | "regulatory"
  | "legal"
  | "financial"
  | "other";

export type AgentType =
  | "digest"
  | "monitor"
  | "investigator"
  | "artifact_drafter";

export type AgentStatus =
  | "scheduled"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type ReviewStatus = "pending" | "approved" | "rejected";

export type ArtifactType =
  | "brief"
  | "report"
  | "analysis"
  | "summary"
  | "timeline"
  | "comparison";

export type ArtifactStatus = "draft" | "pending_review" | "approved" | "rejected";

// ============================================================================
// Core Domain Types
// ============================================================================

export interface SubjectConfig {
  keywords: string[];
  entities: string[];
  sources: string[];
  alert_thresholds?: Record<string, unknown> | null;
  collection_schedule?: string | null;
  is_active: boolean;
  last_collection_at?: string | null;
}

export interface Subject {
  id: string;
  name: string;
  type?: "person" | "organization" | "topic" | "event" | "product";
  subject_type?: string;
  description?: string;
  aliases?: string[];
  metadata?: Record<string, unknown>;
  owner_id?: string;
  organization_id?: string | null;
  is_archived?: boolean;
  config?: SubjectConfig;
  created_at: string;
  updated_at: string;
}

export interface Source {
  id: string;
  name: string;
  type: SourceType;
  url?: string;
  credibility_score: number;
  bias_indicators: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Item {
  id: string;
  type: ItemType;
  title: string;
  content: string;
  summary?: string;
  url?: string;
  source: Source;
  published_at: string;
  ingested_at: string;
  sentiment: Sentiment;
  sentiment_score: number;
  entities: Entity[];
  claims: Claim[];
  provenance: Provenance;
  metadata: Record<string, unknown>;
}

export interface Entity {
  id: string;
  name: string;
  type: string;
  salience: number;
  mentions: number;
  sentiment?: Sentiment;
}

export interface Claim {
  id: string;
  text: string;
  type: "factual" | "opinion" | "prediction" | "quote";
  speaker?: string;
  confidence: number;
  supporting_items: string[];
  contradicting_items: string[];
  verified?: boolean;
}

export interface Provenance {
  item_id: string;
  source_id: string;
  url: string;
  retrieved_at: string;
  extraction_method: string;
  confidence: number;
}

// ============================================================================
// Narrative Types
// ============================================================================

export interface Narrative {
  id: string;
  subject_id: string;
  thesis: string;
  summary: string;
  lifecycle_stage: LifecycleStage;
  first_seen: string;
  last_seen: string;
  peak_date?: string;
  item_count: number;
  source_count: number;
  amplifiers: Amplifier[];
  supporting_claims: Claim[];
  contradicting_claims: Claim[];
  origin_item?: Item;
  sentiment_breakdown: SentimentBreakdown;
  prevalence_history: PrevalencePoint[];
  lifecycle_history: LifecyclePoint[];
  created_at: string;
  updated_at: string;
}

export interface Amplifier {
  entity_id: string;
  entity_name: string;
  entity_type: string;
  amplification_score: number;
  item_count: number;
  first_mention: string;
  last_mention: string;
}

export interface SentimentBreakdown {
  positive: number;
  neutral: number;
  negative: number;
  mixed: number;
}

export interface PrevalencePoint {
  date: string;
  count: number;
  percentage: number;
}

export interface LifecyclePoint {
  date: string;
  stage: LifecycleStage;
  velocity: number;
}

// ============================================================================
// Event Types
// ============================================================================

export interface Event {
  id: string;
  subject_id: string;
  type: EventType;
  title: string;
  description: string;
  occurred_at: string;
  significance: number;
  actors: Entity[];
  locations: string[];
  supporting_items: Item[];
  related_narratives: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TimelineEvent extends Event {
  position: number;
  connections: string[];
}

// ============================================================================
// Digest Types
// ============================================================================

export interface Digest {
  id: string;
  subject_id: string;
  period_start: string;
  period_end: string;
  summary: string;
  key_developments: Development[];
  narrative_updates: NarrativeUpdate[];
  notable_items: Item[];
  sentiment_summary: SentimentSummary;
  metrics: DigestMetrics;
  created_at: string;
}

export interface Development {
  title: string;
  description: string;
  significance: number;
  items: string[];
}

export interface NarrativeUpdate {
  narrative_id: string;
  thesis: string;
  previous_stage: LifecycleStage;
  current_stage: LifecycleStage;
  change_summary: string;
}

export interface SentimentSummary {
  overall: Sentiment;
  trend: "improving" | "stable" | "declining";
  breakdown: SentimentBreakdown;
}

export interface DigestMetrics {
  total_items: number;
  new_sources: number;
  new_narratives: number;
  updated_narratives: number;
}

// ============================================================================
// Search Types
// ============================================================================

export interface SearchQuery {
  q: string;
  subject_id?: string;
  source_ids?: string[];
  item_types?: ItemType[];
  sentiment?: Sentiment[];
  date_from?: string;
  date_to?: string;
  sort_by?: "relevance" | "date" | "sentiment";
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export interface SearchResult {
  items: Item[];
  total: number;
  page: number;
  page_size: number;
  facets: SearchFacets;
}

export interface SearchFacets {
  sources: FacetCount[];
  types: FacetCount[];
  sentiments: FacetCount[];
  dates: FacetCount[];
}

export interface FacetCount {
  value: string;
  count: number;
}

// ============================================================================
// Artifact Types
// ============================================================================

export interface Artifact {
  id: string;
  type: ArtifactType;
  title: string;
  content: string;
  status: ArtifactStatus;
  subject_id: string;
  narrative_ids: string[];
  item_ids: string[];
  citations: Citation[];
  version: number;
  created_by: string;
  reviewed_by?: string;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  id: string;
  item_id: string;
  text: string;
  position: number;
  item?: Item;
}

export interface ArtifactRequest {
  type: ArtifactType;
  title: string;
  subject_id: string;
  instructions: string;
  narrative_ids?: string[];
  item_ids?: string[];
}

// ============================================================================
// Agent Types
// ============================================================================

export interface Agent {
  id: string;
  type: AgentType;
  name: string;
  description?: string;
  subject_id?: string;
  schedule?: AgentSchedule;
  config: Record<string, unknown>;
  status: AgentStatus;
  last_run?: AgentRun;
  created_at: string;
  updated_at: string;
}

export interface AgentSchedule {
  cron: string;
  timezone: string;
  enabled: boolean;
  next_run?: string;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  status: AgentStatus;
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
  input: Record<string, unknown>;
  output?: Record<string, unknown>;
  traces: AgentTrace[];
  cost?: AgentCost;
  error?: string;
}

export interface AgentTrace {
  timestamp: string;
  level: "debug" | "info" | "warn" | "error";
  message: string;
  data?: Record<string, unknown>;
}

export interface AgentCost {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface InvestigatorRequest {
  subject_id: string;
  question: string;
  depth: "shallow" | "medium" | "deep";
  time_bound?: string;
}

// ============================================================================
// Review Types
// ============================================================================

export interface ReviewItem {
  id: string;
  type: "narrative" | "claim" | "artifact" | "entity";
  item_id: string;
  status: ReviewStatus;
  priority: "low" | "medium" | "high" | "critical";
  reason: string;
  data: Record<string, unknown>;
  assigned_to?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  notes?: string;
  created_at: string;
}

export interface ReviewAction {
  action: "approve" | "reject";
  notes?: string;
  modifications?: Record<string, unknown>;
}

// ============================================================================
// API Response Types
// ============================================================================

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

// ============================================================================
// Dashboard Types
// ============================================================================

export interface CountStats {
  total: number;
  active: number;
  new_today: number;
  new_this_week: number;
}

export interface NarrativeStats {
  total: number;
  by_lifecycle: Record<string, number>;
  avg_prevalence: number;
  trending_count: number;
}

export interface AgentStats {
  total_runs: number;
  completed: number;
  failed: number;
  running: number;
  total_tokens_today: number;
  total_cost_today_usd: number;
}

export interface SentimentDistribution {
  positive: number;
  neutral: number;
  negative: number;
}

export interface DashboardStats {
  subjects: CountStats;
  items: CountStats;
  events: CountStats;
  narratives: NarrativeStats;
  artifacts: CountStats;
  agents: AgentStats;
  sentiment_distribution: SentimentDistribution;
  generated_at: string;
}

export interface RecentActivity {
  id: string;
  type: string;
  title: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export interface RecentActivityResponse {
  activities: RecentActivity[];
  total_count: number;
  generated_at: string;
}

// ============================================================================
// Chart Data Types
// ============================================================================

export interface ChartDataPoint {
  date: string;
  value: number;
  label?: string;
}

export interface SentimentChartData {
  date: string;
  positive: number;
  neutral: number;
  negative: number;
  mixed: number;
}

export interface LifecycleChartData {
  date: string;
  stage: LifecycleStage;
  velocity: number;
}
