"use client";

export const dynamic = "force-dynamic";

import React, { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Calendar,
  Filter,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  List,
  LayoutGrid,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Modal";
import { EventCard } from "@/components/domain/EventCard";
import { ItemCard } from "@/components/domain/ItemCard";
import { getEvents, getSubjects, getEventsBySubject } from "@/lib/api";
import { formatDate, formatDateTime, cn } from "@/lib/utils";
import { Event, EventType, Subject } from "@/types";

const eventTypeColors: Record<EventType, string> = {
  publication: "bg-blue-500",
  statement: "bg-purple-500",
  action: "bg-amber-500",
  announcement: "bg-green-500",
  regulatory: "bg-red-500",
  legal: "bg-red-400",
  financial: "bg-emerald-500",
  other: "bg-gray-500",
};

export default function TimelinePage() {
  const searchParams = useSearchParams();
  const initialSubjectId = searchParams.get("subject_id");

  const [selectedSubject, setSelectedSubject] = useState<string>(
    initialSubjectId || "all"
  );
  const [viewMode, setViewMode] = useState<"timeline" | "list">("timeline");
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [dateRange, setDateRange] = useState<{ start: string; end: string }>({
    start: "",
    end: "",
  });
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const { data: subjects } = useQuery({
    queryKey: ["subjects-list"],
    queryFn: () => getSubjects(1, 100),
  });

  const { data: events, isLoading } = useQuery({
    queryKey: ["events", selectedSubject],
    queryFn: () =>
      selectedSubject === "all"
        ? getEvents(undefined, 1, 100)
        : getEventsBySubject(selectedSubject, 1, 100),
  });

  const filteredEvents =
    events?.items.filter((event) => {
      const matchesType = typeFilter === "all" || event.type === typeFilter;
      const matchesDateStart =
        !dateRange.start || new Date(event.occurred_at) >= new Date(dateRange.start);
      const matchesDateEnd =
        !dateRange.end || new Date(event.occurred_at) <= new Date(dateRange.end);
      return matchesType && matchesDateStart && matchesDateEnd;
    }) ?? [];

  // Group events by date
  const eventsByDate = filteredEvents.reduce((acc, event) => {
    const date = formatDate(event.occurred_at, "yyyy-MM-dd");
    if (!acc[date]) {
      acc[date] = [];
    }
    acc[date].push(event);
    return acc;
  }, {} as Record<string, Event[]>);

  const sortedDates = Object.keys(eventsByDate).sort(
    (a, b) => new Date(b).getTime() - new Date(a).getTime()
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Timeline</h1>
          <p className="text-gray-500 mt-1">
            Explore events and developments chronologically
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={viewMode === "timeline" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("timeline")}
          >
            <Calendar className="h-4 w-4 mr-2" />
            Timeline
          </Button>
          <Button
            variant={viewMode === "list" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("list")}
          >
            <List className="h-4 w-4 mr-2" />
            List
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Subject
              </label>
              <Select value={selectedSubject} onValueChange={setSelectedSubject}>
                <SelectTrigger>
                  <SelectValue placeholder="Select subject" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Subjects</SelectItem>
                  {subjects?.items.map((subject) => (
                    <SelectItem key={subject.id} value={subject.id}>
                      {subject.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Event Type
              </label>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="publication">Publication</SelectItem>
                  <SelectItem value="statement">Statement</SelectItem>
                  <SelectItem value="action">Action</SelectItem>
                  <SelectItem value="announcement">Announcement</SelectItem>
                  <SelectItem value="regulatory">Regulatory</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                  <SelectItem value="financial">Financial</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                From
              </label>
              <Input
                type="date"
                value={dateRange.start}
                onChange={(e) =>
                  setDateRange({ ...dateRange, start: e.target.value })
                }
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                To
              </label>
              <Input
                type="date"
                value={dateRange.end}
                onChange={(e) =>
                  setDateRange({ ...dateRange, end: e.target.value })
                }
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-24 skeleton rounded-xl" />
          ))}
        </div>
      ) : filteredEvents.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Calendar className="h-12 w-12 text-gray-300 mx-auto" />
            <p className="mt-4 text-gray-900 font-medium">No events found</p>
            <p className="text-sm text-gray-500">
              Try adjusting your filters or selecting a different subject
            </p>
          </CardContent>
        </Card>
      ) : viewMode === "timeline" ? (
        <div className="relative">
          {/* Timeline Line */}
          <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-200" />

          {/* Events */}
          <div className="space-y-6">
            {sortedDates.map((date) => (
              <div key={date} className="relative">
                {/* Date Header */}
                <div className="flex items-center gap-4 mb-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white border-2 border-lantern-500 z-10">
                    <Calendar className="h-5 w-5 text-lantern-600" />
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900">
                    {formatDate(date, "EEEE, MMMM d, yyyy")}
                  </h3>
                  <Badge variant="secondary">
                    {eventsByDate[date].length} event
                    {eventsByDate[date].length !== 1 ? "s" : ""}
                  </Badge>
                </div>

                {/* Events for this date */}
                <div className="ml-16 space-y-3">
                  {eventsByDate[date]
                    .sort(
                      (a, b) =>
                        new Date(b.occurred_at).getTime() -
                        new Date(a.occurred_at).getTime()
                    )
                    .map((event) => (
                      <div key={event.id} className="relative">
                        {/* Connector */}
                        <div className="absolute -left-10 top-4 w-4 h-0.5 bg-gray-200" />
                        <div
                          className={cn(
                            "absolute -left-12 top-3 w-4 h-4 rounded-full",
                            eventTypeColors[event.type]
                          )}
                        />

                        <EventCard
                          event={event}
                          onSelect={setSelectedEvent}
                          selected={selectedEvent?.id === event.id}
                        />
                      </div>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredEvents
            .sort(
              (a, b) =>
                new Date(b.occurred_at).getTime() -
                new Date(a.occurred_at).getTime()
            )
            .map((event) => (
              <EventCard
                key={event.id}
                event={event}
                onSelect={setSelectedEvent}
                selected={selectedEvent?.id === event.id}
              />
            ))}
        </div>
      )}

      {/* Event Detail Modal */}
      <Dialog
        open={!!selectedEvent}
        onOpenChange={() => setSelectedEvent(null)}
      >
        <DialogContent className="max-w-2xl">
          {selectedEvent && (
            <>
              <DialogHeader>
                <DialogTitle>{selectedEvent.title}</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <p className="text-gray-600">{selectedEvent.description}</p>

                <div className="flex items-center gap-4 text-sm text-gray-500">
                  <span>{formatDateTime(selectedEvent.occurred_at)}</span>
                  <Badge variant="outline" className="capitalize">
                    {selectedEvent.type}
                  </Badge>
                  <Badge
                    variant={
                      selectedEvent.significance >= 0.8
                        ? "danger"
                        : selectedEvent.significance >= 0.5
                        ? "warning"
                        : "secondary"
                    }
                  >
                    {Math.round(selectedEvent.significance * 100)}% significance
                  </Badge>
                </div>

                {selectedEvent.actors.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-900 mb-2">
                      Actors
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedEvent.actors.map((actor) => (
                        <Badge key={actor.id} variant="outline">
                          {actor.name}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {selectedEvent.locations.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-900 mb-2">
                      Locations
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedEvent.locations.map((location, i) => (
                        <Badge key={i} variant="secondary">
                          {location}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {selectedEvent.supporting_items.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-900 mb-2">
                      Supporting Evidence ({selectedEvent.supporting_items.length})
                    </h4>
                    <div className="space-y-3 max-h-60 overflow-y-auto">
                      {selectedEvent.supporting_items.map((item) => (
                        <ItemCard key={item.id} item={item} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
