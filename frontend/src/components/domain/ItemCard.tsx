"use client";

import React from "react";
import Link from "next/link";
import {
  FileText,
  MessageCircle,
  Video,
  Mic,
  File,
  Newspaper,
  BookOpen,
  ExternalLink,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Item, ItemType } from "@/types";
import {
  cn,
  formatRelativeTime,
  getSentimentBgColor,
  truncate,
} from "@/lib/utils";

interface ItemCardProps {
  item: Item;
  showProvenance?: boolean;
  className?: string;
}

const typeIcons: Record<ItemType, React.ComponentType<{ className?: string }>> = {
  article: Newspaper,
  social_post: MessageCircle,
  video: Video,
  podcast: Mic,
  document: FileText,
  press_release: File,
  filing: FileText,
  research: BookOpen,
  other: File,
};

const typeLabels: Record<ItemType, string> = {
  article: "Article",
  social_post: "Social",
  video: "Video",
  podcast: "Podcast",
  document: "Document",
  press_release: "Press Release",
  filing: "Filing",
  research: "Research",
  other: "Other",
};

export function ItemCard({ item, showProvenance = true, className }: ItemCardProps) {
  const Icon = typeIcons[item.type] || File;

  return (
    <Card className={cn("hover:shadow-medium transition-shadow", className)}>
      <CardContent className="p-4">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-gray-100">
            <Icon className="h-5 w-5 text-gray-600" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium text-gray-900 line-clamp-2">
                {item.title}
              </h3>
              <Badge className={cn(getSentimentBgColor(item.sentiment), "flex-shrink-0")}>
                {item.sentiment}
              </Badge>
            </div>
            {item.summary && (
              <p className="text-sm text-gray-500 mt-1 line-clamp-2">
                {truncate(item.summary, 150)}
              </p>
            )}
          </div>
        </div>

        {/* Source & Time */}
        <div className="mt-3 flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              {typeLabels[item.type]}
            </Badge>
            {showProvenance && item.source && (
              <span className="text-gray-500">{item.source.name}</span>
            )}
          </div>
          <span className="text-xs text-gray-400">
            {formatRelativeTime(item.published_at)}
          </span>
        </div>

        {/* Entities */}
        {item.entities.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <div className="flex items-center gap-2 flex-wrap">
              {item.entities.slice(0, 4).map((entity) => (
                <Badge key={entity.id} variant="secondary" className="text-xs">
                  {entity.name}
                </Badge>
              ))}
              {item.entities.length > 4 && (
                <Badge variant="secondary" className="text-xs">
                  +{item.entities.length - 4}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* External Link */}
        {item.url && (
          <div className="mt-3">
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-lantern-600 hover:text-lantern-700"
              onClick={(e) => e.stopPropagation()}
            >
              View source
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
