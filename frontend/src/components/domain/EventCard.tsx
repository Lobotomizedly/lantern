"use client";

import React from "react";
import {
  Calendar,
  MapPin,
  Users,
  AlertCircle,
  FileText,
  Briefcase,
  Scale,
  DollarSign,
  Megaphone,
  BookOpen,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Event, EventType } from "@/types";
import { cn, formatDateTime, truncate } from "@/lib/utils";

interface EventCardProps {
  event: Event;
  onSelect?: (event: Event) => void;
  selected?: boolean;
  compact?: boolean;
  className?: string;
}

const typeIcons: Record<EventType, React.ComponentType<{ className?: string }>> = {
  publication: FileText,
  statement: Megaphone,
  action: AlertCircle,
  announcement: Megaphone,
  regulatory: Scale,
  legal: Scale,
  financial: DollarSign,
  other: BookOpen,
};

const typeColors: Record<EventType, string> = {
  publication: "bg-blue-100 text-blue-800",
  statement: "bg-purple-100 text-purple-800",
  action: "bg-amber-100 text-amber-800",
  announcement: "bg-green-100 text-green-800",
  regulatory: "bg-red-100 text-red-800",
  legal: "bg-red-100 text-red-800",
  financial: "bg-emerald-100 text-emerald-800",
  other: "bg-gray-100 text-gray-800",
};

export function EventCard({
  event,
  onSelect,
  selected = false,
  compact = false,
  className,
}: EventCardProps) {
  const Icon = typeIcons[event.type] || BookOpen;

  const significanceColor =
    event.significance >= 0.8
      ? "text-red-600"
      : event.significance >= 0.5
      ? "text-amber-600"
      : "text-gray-500";

  if (compact) {
    return (
      <div
        className={cn(
          "flex items-center gap-3 p-3 rounded-lg border transition-colors cursor-pointer",
          selected
            ? "border-lantern-500 bg-lantern-50"
            : "border-gray-200 hover:border-gray-300 hover:bg-gray-50",
          className
        )}
        onClick={() => onSelect?.(event)}
      >
        <div
          className={cn(
            "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full",
            typeColors[event.type]
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">
            {event.title}
          </p>
          <p className="text-xs text-gray-500">
            {formatDateTime(event.occurred_at)}
          </p>
        </div>
        <div className={cn("text-xs font-medium", significanceColor)}>
          {Math.round(event.significance * 100)}%
        </div>
      </div>
    );
  }

  return (
    <Card
      className={cn(
        "transition-all cursor-pointer",
        selected
          ? "ring-2 ring-lantern-500 shadow-medium"
          : "hover:shadow-medium",
        className
      )}
      onClick={() => onSelect?.(event)}
    >
      <CardContent className="p-4">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg",
              typeColors[event.type]
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium text-gray-900">{event.title}</h3>
              <Badge variant="outline" className={cn("flex-shrink-0", significanceColor)}>
                {Math.round(event.significance * 100)}% significant
              </Badge>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {truncate(event.description, 200)}
            </p>
          </div>
        </div>

        {/* Meta */}
        <div className="mt-4 flex items-center gap-4 text-sm text-gray-500">
          <span className="flex items-center gap-1">
            <Calendar className="h-4 w-4" />
            {formatDateTime(event.occurred_at)}
          </span>
          {event.locations.length > 0 && (
            <span className="flex items-center gap-1">
              <MapPin className="h-4 w-4" />
              {event.locations[0]}
              {event.locations.length > 1 && ` +${event.locations.length - 1}`}
            </span>
          )}
        </div>

        {/* Actors */}
        {event.actors.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-gray-400" />
              <div className="flex gap-1 flex-wrap">
                {event.actors.slice(0, 4).map((actor) => (
                  <Badge key={actor.id} variant="secondary" className="text-xs">
                    {actor.name}
                  </Badge>
                ))}
                {event.actors.length > 4 && (
                  <Badge variant="secondary" className="text-xs">
                    +{event.actors.length - 4}
                  </Badge>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Supporting Items Count */}
        {event.supporting_items && event.supporting_items.length > 0 && (
          <div className="mt-2 text-xs text-gray-500">
            {event.supporting_items.length} supporting item
            {event.supporting_items.length !== 1 ? "s" : ""}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
