import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { format, formatDistanceToNow, parseISO } from "date-fns";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date, formatStr = "MMM d, yyyy"): string {
  const d = typeof date === "string" ? parseISO(date) : date;
  return format(d, formatStr);
}

export function formatDateTime(date: string | Date): string {
  const d = typeof date === "string" ? parseISO(date) : date;
  return format(d, "MMM d, yyyy 'at' h:mm a");
}

export function formatRelativeTime(date: string | Date): string {
  const d = typeof date === "string" ? parseISO(date) : date;
  return formatDistanceToNow(d, { addSuffix: true });
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + "...";
}

export function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
}

export function formatNumber(num: number): string {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + "M";
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + "K";
  }
  return num.toString();
}

export function formatPercentage(num: number, decimals = 1): string {
  return (num * 100).toFixed(decimals) + "%";
}

export function formatCurrency(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount);
}

export function getSentimentColor(sentiment: string): string {
  const colors: Record<string, string> = {
    positive: "text-sentiment-positive",
    neutral: "text-sentiment-neutral",
    negative: "text-sentiment-negative",
    mixed: "text-sentiment-mixed",
  };
  return colors[sentiment] || colors.neutral;
}

export function getSentimentBgColor(sentiment: string): string {
  const colors: Record<string, string> = {
    positive: "bg-green-100 text-green-800",
    neutral: "bg-gray-100 text-gray-800",
    negative: "bg-red-100 text-red-800",
    mixed: "bg-amber-100 text-amber-800",
  };
  return colors[sentiment] || colors.neutral;
}

export function getLifecycleColor(stage: string): string {
  const colors: Record<string, string> = {
    emerging: "text-lifecycle-emerging",
    growing: "text-lifecycle-growing",
    peak: "text-lifecycle-peak",
    declining: "text-lifecycle-declining",
    dormant: "text-lifecycle-dormant",
  };
  return colors[stage] || colors.dormant;
}

export function getLifecycleBgColor(stage: string): string {
  const colors: Record<string, string> = {
    emerging: "bg-blue-100 text-blue-800",
    growing: "bg-green-100 text-green-800",
    peak: "bg-amber-100 text-amber-800",
    declining: "bg-red-100 text-red-800",
    dormant: "bg-gray-100 text-gray-800",
  };
  return colors[stage] || colors.dormant;
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    scheduled: "bg-blue-100 text-blue-800",
    running: "bg-amber-100 text-amber-800",
    completed: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    cancelled: "bg-gray-100 text-gray-800",
    pending: "bg-amber-100 text-amber-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
    draft: "bg-gray-100 text-gray-800",
    pending_review: "bg-amber-100 text-amber-800",
  };
  return colors[status] || colors.pending;
}

export function getPriorityColor(priority: string): string {
  const colors: Record<string, string> = {
    low: "bg-gray-100 text-gray-800",
    medium: "bg-blue-100 text-blue-800",
    high: "bg-amber-100 text-amber-800",
    critical: "bg-red-100 text-red-800",
  };
  return colors[priority] || colors.medium;
}

export function debounce<T extends (...args: never[]) => unknown>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout | null = null;

  return function executedFunction(...args: Parameters<T>) {
    const later = () => {
      timeout = null;
      func(...args);
    };

    if (timeout) {
      clearTimeout(timeout);
    }
    timeout = setTimeout(later, wait);
  };
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 15);
}
