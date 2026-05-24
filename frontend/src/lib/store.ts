import { create } from "zustand";
import { persist } from "zustand/middleware";
import { Subject, SearchQuery } from "@/types";

// ============================================================================
// UI Store
// ============================================================================

interface UIState {
  sidebarOpen: boolean;
  sidebarCollapsed: boolean;
  theme: "light" | "dark" | "system";
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebarCollapsed: () => void;
  setTheme: (theme: "light" | "dark" | "system") => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      sidebarCollapsed: false,
      theme: "light",
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      toggleSidebarCollapsed: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: "lantern-ui-storage",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
      }),
    }
  )
);

// ============================================================================
// Subject Store
// ============================================================================

interface SubjectState {
  subjects: Subject[];
  selectedSubject: Subject | null;
  setSubjects: (subjects: Subject[]) => void;
  setSelectedSubject: (subject: Subject | null) => void;
  addSubject: (subject: Subject) => void;
  updateSubject: (id: string, updates: Partial<Subject>) => void;
  removeSubject: (id: string) => void;
}

export const useSubjectStore = create<SubjectState>()((set) => ({
  subjects: [],
  selectedSubject: null,
  setSubjects: (subjects) => set({ subjects }),
  setSelectedSubject: (selectedSubject) => set({ selectedSubject }),
  addSubject: (subject) =>
    set((state) => ({ subjects: [...state.subjects, subject] })),
  updateSubject: (id, updates) =>
    set((state) => ({
      subjects: state.subjects.map((s) => (s.id === id ? { ...s, ...updates } : s)),
      selectedSubject:
        state.selectedSubject?.id === id
          ? { ...state.selectedSubject, ...updates }
          : state.selectedSubject,
    })),
  removeSubject: (id) =>
    set((state) => ({
      subjects: state.subjects.filter((s) => s.id !== id),
      selectedSubject:
        state.selectedSubject?.id === id ? null : state.selectedSubject,
    })),
}));

// ============================================================================
// Search Store
// ============================================================================

interface SearchState {
  query: SearchQuery;
  recentSearches: string[];
  setQuery: (query: Partial<SearchQuery>) => void;
  resetQuery: () => void;
  addRecentSearch: (search: string) => void;
  clearRecentSearches: () => void;
}

const defaultQuery: SearchQuery = {
  q: "",
  page: 1,
  page_size: 20,
  sort_by: "relevance",
  sort_order: "desc",
};

export const useSearchStore = create<SearchState>()(
  persist(
    (set) => ({
      query: defaultQuery,
      recentSearches: [],
      setQuery: (updates) =>
        set((state) => ({ query: { ...state.query, ...updates } })),
      resetQuery: () => set({ query: defaultQuery }),
      addRecentSearch: (search) =>
        set((state) => ({
          recentSearches: [
            search,
            ...state.recentSearches.filter((s) => s !== search),
          ].slice(0, 10),
        })),
      clearRecentSearches: () => set({ recentSearches: [] }),
    }),
    {
      name: "lantern-search-storage",
      partialize: (state) => ({ recentSearches: state.recentSearches }),
    }
  )
);

// ============================================================================
// Notification Store
// ============================================================================

export interface Notification {
  id: string;
  type: "success" | "error" | "warning" | "info";
  title: string;
  message?: string;
  duration?: number;
}

interface NotificationState {
  notifications: Notification[];
  addNotification: (notification: Omit<Notification, "id">) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;
}

export const useNotificationStore = create<NotificationState>()((set) => ({
  notifications: [],
  addNotification: (notification) =>
    set((state) => ({
      notifications: [
        ...state.notifications,
        { ...notification, id: Math.random().toString(36).substring(7) },
      ],
    })),
  removeNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),
  clearNotifications: () => set({ notifications: [] }),
}));

// ============================================================================
// Agent Watch Store
// ============================================================================

interface WatchedRun {
  agentId: string;
  runId: string;
  agentName: string;
}

interface AgentWatchState {
  watchedRuns: WatchedRun[];
  addWatchedRun: (run: WatchedRun) => void;
  removeWatchedRun: (runId: string) => void;
  clearWatchedRuns: () => void;
}

export const useAgentWatchStore = create<AgentWatchState>()((set) => ({
  watchedRuns: [],
  addWatchedRun: (run) =>
    set((state) => ({
      watchedRuns: [...state.watchedRuns.filter((r) => r.runId !== run.runId), run],
    })),
  removeWatchedRun: (runId) =>
    set((state) => ({
      watchedRuns: state.watchedRuns.filter((r) => r.runId !== runId),
    })),
  clearWatchedRuns: () => set({ watchedRuns: [] }),
}));
