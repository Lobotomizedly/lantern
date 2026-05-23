"use client";

import React from "react";
import { X, Calendar, Filter } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Checkbox } from "@/components/ui/Checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Badge } from "@/components/ui/Badge";
import { SearchQuery, Sentiment, ItemType, Source } from "@/types";
import { cn, capitalize } from "@/lib/utils";

interface SearchFiltersProps {
  query: SearchQuery;
  sources: Source[];
  onQueryChange: (updates: Partial<SearchQuery>) => void;
  onReset: () => void;
  className?: string;
}

const sentimentOptions: Sentiment[] = ["positive", "neutral", "negative", "mixed"];
const itemTypeOptions: ItemType[] = [
  "article",
  "social_post",
  "video",
  "podcast",
  "document",
  "press_release",
  "filing",
  "research",
];

const itemTypeLabels: Record<ItemType, string> = {
  article: "Article",
  social_post: "Social Post",
  video: "Video",
  podcast: "Podcast",
  document: "Document",
  press_release: "Press Release",
  filing: "Filing",
  research: "Research",
  other: "Other",
};

export function SearchFilters({
  query,
  sources,
  onQueryChange,
  onReset,
  className,
}: SearchFiltersProps) {
  const activeFiltersCount =
    (query.sentiment?.length || 0) +
    (query.item_types?.length || 0) +
    (query.source_ids?.length || 0) +
    (query.date_from ? 1 : 0) +
    (query.date_to ? 1 : 0);

  const toggleSentiment = (sentiment: Sentiment) => {
    const current = query.sentiment || [];
    const updated = current.includes(sentiment)
      ? current.filter((s) => s !== sentiment)
      : [...current, sentiment];
    onQueryChange({ sentiment: updated.length ? updated : undefined });
  };

  const toggleItemType = (type: ItemType) => {
    const current = query.item_types || [];
    const updated = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    onQueryChange({ item_types: updated.length ? updated : undefined });
  };

  const toggleSource = (sourceId: string) => {
    const current = query.source_ids || [];
    const updated = current.includes(sourceId)
      ? current.filter((s) => s !== sourceId)
      : [...current, sourceId];
    onQueryChange({ source_ids: updated.length ? updated : undefined });
  };

  return (
    <div className={cn("space-y-6", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Filter className="h-5 w-5 text-gray-500" />
          <h3 className="font-medium text-gray-900">Filters</h3>
          {activeFiltersCount > 0 && (
            <Badge variant="primary">{activeFiltersCount}</Badge>
          )}
        </div>
        {activeFiltersCount > 0 && (
          <Button variant="ghost" size="sm" onClick={onReset}>
            Clear all
          </Button>
        )}
      </div>

      {/* Sort */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Sort by
        </label>
        <Select
          value={query.sort_by || "relevance"}
          onValueChange={(value) =>
            onQueryChange({ sort_by: value as SearchQuery["sort_by"] })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="relevance">Relevance</SelectItem>
            <SelectItem value="date">Date</SelectItem>
            <SelectItem value="sentiment">Sentiment</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Date Range */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Date range
        </label>
        <div className="space-y-2">
          <div className="relative">
            <Input
              type="date"
              value={query.date_from || ""}
              onChange={(e) =>
                onQueryChange({ date_from: e.target.value || undefined })
              }
              placeholder="From"
              icon={<Calendar className="h-4 w-4" />}
            />
          </div>
          <div className="relative">
            <Input
              type="date"
              value={query.date_to || ""}
              onChange={(e) =>
                onQueryChange({ date_to: e.target.value || undefined })
              }
              placeholder="To"
              icon={<Calendar className="h-4 w-4" />}
            />
          </div>
        </div>
      </div>

      {/* Sentiment */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Sentiment
        </label>
        <div className="space-y-2">
          {sentimentOptions.map((sentiment) => (
            <label
              key={sentiment}
              className="flex items-center gap-2 cursor-pointer"
            >
              <Checkbox
                checked={query.sentiment?.includes(sentiment) || false}
                onCheckedChange={() => toggleSentiment(sentiment)}
              />
              <span className="text-sm text-gray-700">{capitalize(sentiment)}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Item Types */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Content type
        </label>
        <div className="space-y-2">
          {itemTypeOptions.map((type) => (
            <label key={type} className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={query.item_types?.includes(type) || false}
                onCheckedChange={() => toggleItemType(type)}
              />
              <span className="text-sm text-gray-700">{itemTypeLabels[type]}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Sources */}
      {sources.length > 0 && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Sources
          </label>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {sources.map((source) => (
              <label
                key={source.id}
                className="flex items-center gap-2 cursor-pointer"
              >
                <Checkbox
                  checked={query.source_ids?.includes(source.id) || false}
                  onCheckedChange={() => toggleSource(source.id)}
                />
                <span className="text-sm text-gray-700 truncate">
                  {source.name}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Active Filters Summary */}
      {activeFiltersCount > 0 && (
        <div className="pt-4 border-t border-gray-200">
          <p className="text-sm text-gray-500 mb-2">Active filters:</p>
          <div className="flex flex-wrap gap-2">
            {query.sentiment?.map((s) => (
              <Badge
                key={s}
                variant="outline"
                className="flex items-center gap-1 cursor-pointer"
                onClick={() => toggleSentiment(s)}
              >
                {capitalize(s)}
                <X className="h-3 w-3" />
              </Badge>
            ))}
            {query.item_types?.map((t) => (
              <Badge
                key={t}
                variant="outline"
                className="flex items-center gap-1 cursor-pointer"
                onClick={() => toggleItemType(t)}
              >
                {itemTypeLabels[t]}
                <X className="h-3 w-3" />
              </Badge>
            ))}
            {query.date_from && (
              <Badge
                variant="outline"
                className="flex items-center gap-1 cursor-pointer"
                onClick={() => onQueryChange({ date_from: undefined })}
              >
                From: {query.date_from}
                <X className="h-3 w-3" />
              </Badge>
            )}
            {query.date_to && (
              <Badge
                variant="outline"
                className="flex items-center gap-1 cursor-pointer"
                onClick={() => onQueryChange({ date_to: undefined })}
              >
                To: {query.date_to}
                <X className="h-3 w-3" />
              </Badge>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
