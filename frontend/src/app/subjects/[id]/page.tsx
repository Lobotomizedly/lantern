"use client";

import React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Calendar,
  TrendingUp,
  MessageSquare,
  FileText,
  RefreshCw,
  ExternalLink,
  Clock,
  Users,
  Building,
  Tag,
  Package,
  User,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { NarrativeCard } from "@/components/domain/NarrativeCard";
import { ItemCard } from "@/components/domain/ItemCard";
import { SentimentChart } from "@/components/charts/SentimentChart";
import {
  getSubject,
  getNarrativesBySubject,
  getItemsBySubject,
  getLatestDigest,
  generateDigest,
} from "@/lib/api";
import { formatDate, formatRelativeTime, cn } from "@/lib/utils";
import { Subject, SentimentChartData } from "@/types";

const subjectTypeIcons: Record<
  Subject["type"],
  React.ComponentType<{ className?: string }>
> = {
  person: User,
  organization: Building,
  topic: Tag,
  event: Calendar,
  product: Package,
};

export default function SubjectDashboardPage() {
  const params = useParams();
  const subjectId = params.id as string;

  const { data: subject, isLoading: subjectLoading } = useQuery({
    queryKey: ["subject", subjectId],
    queryFn: () => getSubject(subjectId),
  });

  const { data: narratives, isLoading: narrativesLoading } = useQuery({
    queryKey: ["subject-narratives", subjectId],
    queryFn: () => getNarrativesBySubject(subjectId, 1, 10),
  });

  const { data: items, isLoading: itemsLoading } = useQuery({
    queryKey: ["subject-items", subjectId],
    queryFn: () => getItemsBySubject(subjectId, 1, 10),
  });

  const { data: digest, isLoading: digestLoading, refetch: refetchDigest } = useQuery({
    queryKey: ["subject-digest", subjectId],
    queryFn: () => getLatestDigest(subjectId),
  });

  const handleGenerateDigest = async () => {
    try {
      await generateDigest(subjectId);
      refetchDigest();
    } catch (error) {
      console.error("Failed to generate digest:", error);
    }
  };

  // Mock sentiment data for chart
  const sentimentData: SentimentChartData[] = Array.from({ length: 14 }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (13 - i));
    return {
      date: date.toISOString().split("T")[0],
      positive: Math.floor(Math.random() * 30) + 10,
      neutral: Math.floor(Math.random() * 20) + 15,
      negative: Math.floor(Math.random() * 15) + 5,
      mixed: Math.floor(Math.random() * 10) + 5,
    };
  });

  if (subjectLoading) {
    return (
      <div className="space-y-6">
        <div className="h-12 w-64 skeleton rounded-lg" />
        <div className="h-40 skeleton rounded-xl" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-80 skeleton rounded-xl" />
          <div className="h-80 skeleton rounded-xl" />
        </div>
      </div>
    );
  }

  if (!subject) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Subject not found</p>
        <Link href="/subjects">
          <Button className="mt-4">Back to Subjects</Button>
        </Link>
      </div>
    );
  }

  const Icon = subjectTypeIcons[subject.type] || Users;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/subjects">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
              <Icon className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                {subject.name}
              </h1>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="secondary" className="capitalize">
                  {subject.type}
                </Badge>
                {subject.aliases.slice(0, 2).map((alias, i) => (
                  <Badge key={i} variant="outline" className="text-xs">
                    {alias}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        </div>
        <Button variant="outline" onClick={handleGenerateDigest}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Generate Digest
        </Button>
      </div>

      {/* Today's Digest */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              Today&apos;s Digest
            </CardTitle>
            {digest && (
              <span className="text-xs text-gray-500">
                Generated {formatRelativeTime(digest.created_at)}
              </span>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {digestLoading ? (
            <div className="h-24 skeleton rounded-lg" />
          ) : digest ? (
            <div className="space-y-4">
              <p className="text-gray-700">{digest.summary}</p>
              {digest.key_developments.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-900 mb-2">
                    Key Developments
                  </h4>
                  <ul className="space-y-2">
                    {digest.key_developments.map((dev, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <TrendingUp className="h-4 w-4 text-lantern-600 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-sm font-medium text-gray-900">
                            {dev.title}
                          </p>
                          <p className="text-sm text-gray-500">{dev.description}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="flex items-center gap-4 text-sm text-gray-500 pt-2 border-t border-gray-100">
                <span>{digest.metrics.total_items} items analyzed</span>
                <span>{digest.metrics.new_narratives} new narratives</span>
                <span>{digest.metrics.updated_narratives} updated narratives</span>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <Calendar className="h-8 w-8 mx-auto text-gray-300" />
              <p className="mt-2">No digest available for today</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={handleGenerateDigest}
              >
                Generate Now
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - Narratives & Items */}
        <div className="lg:col-span-2 space-y-6">
          <Tabs defaultValue="narratives">
            <TabsList>
              <TabsTrigger value="narratives">
                <MessageSquare className="h-4 w-4 mr-2" />
                Active Narratives
              </TabsTrigger>
              <TabsTrigger value="items">
                <FileText className="h-4 w-4 mr-2" />
                Recent Items
              </TabsTrigger>
            </TabsList>

            <TabsContent value="narratives" className="mt-4">
              {narrativesLoading ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-40 skeleton rounded-xl" />
                  ))}
                </div>
              ) : narratives?.items.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center">
                    <MessageSquare className="h-12 w-12 text-gray-300 mx-auto" />
                    <p className="mt-4 text-gray-900 font-medium">
                      No narratives yet
                    </p>
                    <p className="text-sm text-gray-500">
                      Narratives will appear as content is analyzed
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-4">
                  {narratives?.items.map((narrative) => (
                    <NarrativeCard key={narrative.id} narrative={narrative} />
                  ))}
                  {narratives && narratives.total > 10 && (
                    <Link
                      href={`/search?subject_id=${subjectId}&type=narrative`}
                    >
                      <Button variant="outline" className="w-full">
                        View All {narratives.total} Narratives
                        <ExternalLink className="h-4 w-4 ml-2" />
                      </Button>
                    </Link>
                  )}
                </div>
              )}
            </TabsContent>

            <TabsContent value="items" className="mt-4">
              {itemsLoading ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-32 skeleton rounded-xl" />
                  ))}
                </div>
              ) : items?.items.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center">
                    <FileText className="h-12 w-12 text-gray-300 mx-auto" />
                    <p className="mt-4 text-gray-900 font-medium">
                      No items yet
                    </p>
                    <p className="text-sm text-gray-500">
                      Items will appear as content is ingested
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-4">
                  {items?.items.map((item) => (
                    <ItemCard key={item.id} item={item} />
                  ))}
                  {items && items.total > 10 && (
                    <Link href={`/search?subject_id=${subjectId}`}>
                      <Button variant="outline" className="w-full">
                        View All {items.total} Items
                        <ExternalLink className="h-4 w-4 ml-2" />
                      </Button>
                    </Link>
                  )}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>

        {/* Right Column - Charts & Stats */}
        <div className="space-y-6">
          {/* Sentiment Trend */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Sentiment Trend</CardTitle>
            </CardHeader>
            <CardContent>
              <SentimentChart data={sentimentData} height={200} showLegend={false} />
            </CardContent>
          </Card>

          {/* Quick Stats */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Quick Stats</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Active Narratives</span>
                <span className="font-medium text-gray-900">
                  {narratives?.total ?? 0}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Total Items</span>
                <span className="font-medium text-gray-900">
                  {items?.total ?? 0}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Last Updated</span>
                <span className="text-sm text-gray-700">
                  {formatRelativeTime(subject.updated_at)}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Related Actions */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Link href={`/timeline?subject_id=${subjectId}`}>
                <Button variant="outline" className="w-full justify-start">
                  <Clock className="h-4 w-4 mr-2" />
                  View Timeline
                </Button>
              </Link>
              <Link href={`/search?subject_id=${subjectId}`}>
                <Button variant="outline" className="w-full justify-start">
                  <FileText className="h-4 w-4 mr-2" />
                  Search Content
                </Button>
              </Link>
              <Link href={`/artifacts?subject_id=${subjectId}`}>
                <Button variant="outline" className="w-full justify-start">
                  <FileText className="h-4 w-4 mr-2" />
                  Create Artifact
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
