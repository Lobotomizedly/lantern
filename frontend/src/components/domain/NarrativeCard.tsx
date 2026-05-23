"use client";

import React from "react";
import Link from "next/link";
import { TrendingUp, TrendingDown, Minus, ExternalLink, Users } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Narrative, LifecycleStage } from "@/types";
import { cn, formatRelativeTime, getLifecycleBgColor, truncate } from "@/lib/utils";

interface NarrativeCardProps {
  narrative: Narrative;
  showSubject?: boolean;
  className?: string;
}

const lifecycleLabels: Record<LifecycleStage, string> = {
  emerging: "Emerging",
  growing: "Growing",
  peak: "At Peak",
  declining: "Declining",
  dormant: "Dormant",
};

const lifecycleIcons: Record<LifecycleStage, React.ReactNode> = {
  emerging: <TrendingUp className="h-3 w-3" />,
  growing: <TrendingUp className="h-3 w-3" />,
  peak: <Minus className="h-3 w-3" />,
  declining: <TrendingDown className="h-3 w-3" />,
  dormant: <Minus className="h-3 w-3" />,
};

export function NarrativeCard({
  narrative,
  showSubject = false,
  className,
}: NarrativeCardProps) {
  const sentimentTotal =
    narrative.sentiment_breakdown.positive +
    narrative.sentiment_breakdown.neutral +
    narrative.sentiment_breakdown.negative +
    narrative.sentiment_breakdown.mixed;

  const sentimentPercentages = {
    positive: sentimentTotal
      ? (narrative.sentiment_breakdown.positive / sentimentTotal) * 100
      : 0,
    neutral: sentimentTotal
      ? (narrative.sentiment_breakdown.neutral / sentimentTotal) * 100
      : 0,
    negative: sentimentTotal
      ? (narrative.sentiment_breakdown.negative / sentimentTotal) * 100
      : 0,
    mixed: sentimentTotal
      ? (narrative.sentiment_breakdown.mixed / sentimentTotal) * 100
      : 0,
  };

  return (
    <Link href={`/narratives/${narrative.id}`}>
      <Card
        className={cn(
          "hover:shadow-medium transition-shadow cursor-pointer",
          className
        )}
      >
        <CardContent className="p-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex-1 min-w-0">
              <h3 className="font-medium text-gray-900 line-clamp-2">
                {narrative.thesis}
              </h3>
              {narrative.summary && (
                <p className="text-sm text-gray-500 mt-1 line-clamp-2">
                  {truncate(narrative.summary, 150)}
                </p>
              )}
            </div>
            <Badge className={cn(getLifecycleBgColor(narrative.lifecycle_stage))}>
              <span className="flex items-center gap-1">
                {lifecycleIcons[narrative.lifecycle_stage]}
                {lifecycleLabels[narrative.lifecycle_stage]}
              </span>
            </Badge>
          </div>

          {/* Sentiment Bar */}
          <div className="mb-3">
            <div className="flex h-1.5 rounded-full overflow-hidden bg-gray-100">
              <div
                className="bg-green-500 transition-all"
                style={{ width: `${sentimentPercentages.positive}%` }}
              />
              <div
                className="bg-gray-400 transition-all"
                style={{ width: `${sentimentPercentages.neutral}%` }}
              />
              <div
                className="bg-amber-500 transition-all"
                style={{ width: `${sentimentPercentages.mixed}%` }}
              />
              <div
                className="bg-red-500 transition-all"
                style={{ width: `${sentimentPercentages.negative}%` }}
              />
            </div>
          </div>

          {/* Stats */}
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-4 text-gray-500">
              <span className="flex items-center gap-1">
                <ExternalLink className="h-3.5 w-3.5" />
                {narrative.item_count} items
              </span>
              <span className="flex items-center gap-1">
                <Users className="h-3.5 w-3.5" />
                {narrative.source_count} sources
              </span>
            </div>
            <span className="text-xs text-gray-400">
              {formatRelativeTime(narrative.last_seen)}
            </span>
          </div>

          {/* Top Amplifiers */}
          {narrative.amplifiers.length > 0 && (
            <div className="mt-3 pt-3 border-t border-gray-100">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Top amplifiers:</span>
                <div className="flex gap-1 flex-wrap">
                  {narrative.amplifiers.slice(0, 3).map((amp) => (
                    <Badge key={amp.entity_id} variant="secondary" className="text-xs">
                      {amp.entity_name}
                    </Badge>
                  ))}
                  {narrative.amplifiers.length > 3 && (
                    <Badge variant="secondary" className="text-xs">
                      +{narrative.amplifiers.length - 3}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
