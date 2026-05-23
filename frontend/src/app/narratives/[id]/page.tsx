"use client";

import React, { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Minus,
  Users,
  FileText,
  ExternalLink,
  CheckCircle,
  XCircle,
  Calendar,
  Clock,
  BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { ItemCard } from "@/components/domain/ItemCard";
import { LifecycleChart } from "@/components/charts/LifecycleChart";
import { PrevalenceChart } from "@/components/charts/PrevalenceChart";
import { getNarrative, getNarrativeItems, getSubject } from "@/lib/api";
import {
  formatDate,
  formatRelativeTime,
  getLifecycleBgColor,
  getSentimentBgColor,
  cn,
} from "@/lib/utils";
import { LifecycleStage, Claim } from "@/types";

const lifecycleLabels: Record<LifecycleStage, string> = {
  emerging: "Emerging",
  growing: "Growing",
  peak: "At Peak",
  declining: "Declining",
  dormant: "Dormant",
};

const lifecycleIcons: Record<LifecycleStage, React.ReactNode> = {
  emerging: <TrendingUp className="h-4 w-4" />,
  growing: <TrendingUp className="h-4 w-4" />,
  peak: <Minus className="h-4 w-4" />,
  declining: <TrendingDown className="h-4 w-4" />,
  dormant: <Minus className="h-4 w-4" />,
};

export default function NarrativeDetailPage() {
  const params = useParams();
  const narrativeId = params.id as string;
  const [itemsPage, setItemsPage] = useState(1);

  const { data: narrative, isLoading: narrativeLoading } = useQuery({
    queryKey: ["narrative", narrativeId],
    queryFn: () => getNarrative(narrativeId),
  });

  const { data: subject } = useQuery({
    queryKey: ["subject", narrative?.subject_id],
    queryFn: () => getSubject(narrative!.subject_id),
    enabled: !!narrative?.subject_id,
  });

  const { data: items, isLoading: itemsLoading } = useQuery({
    queryKey: ["narrative-items", narrativeId, itemsPage],
    queryFn: () => getNarrativeItems(narrativeId, itemsPage, 10),
  });

  if (narrativeLoading) {
    return (
      <div className="space-y-6">
        <div className="h-12 w-64 skeleton rounded-lg" />
        <div className="h-40 skeleton rounded-xl" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 h-96 skeleton rounded-xl" />
          <div className="h-96 skeleton rounded-xl" />
        </div>
      </div>
    );
  }

  if (!narrative) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Narrative not found</p>
        <Link href="/search">
          <Button className="mt-4">Back to Search</Button>
        </Link>
      </div>
    );
  }

  const sentimentTotal =
    narrative.sentiment_breakdown.positive +
    narrative.sentiment_breakdown.neutral +
    narrative.sentiment_breakdown.negative +
    narrative.sentiment_breakdown.mixed;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Link href={subject ? `/subjects/${subject.id}` : "/search"}>
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>
        <div className="flex-1">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                {narrative.thesis}
              </h1>
              <div className="flex items-center gap-3 mt-2">
                <Badge className={cn(getLifecycleBgColor(narrative.lifecycle_stage))}>
                  <span className="flex items-center gap-1">
                    {lifecycleIcons[narrative.lifecycle_stage]}
                    {lifecycleLabels[narrative.lifecycle_stage]}
                  </span>
                </Badge>
                {subject && (
                  <Link href={`/subjects/${subject.id}`}>
                    <Badge variant="outline" className="cursor-pointer">
                      {subject.name}
                    </Badge>
                  </Link>
                )}
              </div>
            </div>
          </div>
          {narrative.summary && (
            <p className="mt-4 text-gray-600">{narrative.summary}</p>
          )}
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100 text-blue-600">
                <FileText className="h-5 w-5" />
              </div>
              <div>
                <p className="text-2xl font-semibold text-gray-900">
                  {narrative.item_count}
                </p>
                <p className="text-sm text-gray-500">Items</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100 text-purple-600">
                <Users className="h-5 w-5" />
              </div>
              <div>
                <p className="text-2xl font-semibold text-gray-900">
                  {narrative.source_count}
                </p>
                <p className="text-sm text-gray-500">Sources</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100 text-green-600">
                <Calendar className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">
                  {formatDate(narrative.first_seen)}
                </p>
                <p className="text-sm text-gray-500">First Seen</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100 text-amber-600">
                <Clock className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">
                  {formatRelativeTime(narrative.last_seen)}
                </p>
                <p className="text-sm text-gray-500">Last Seen</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column */}
        <div className="lg:col-span-2 space-y-6">
          {/* Lifecycle Timeline */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                Lifecycle Timeline
              </CardTitle>
            </CardHeader>
            <CardContent>
              {narrative.lifecycle_history.length > 0 ? (
                <LifecycleChart data={narrative.lifecycle_history} height={200} />
              ) : (
                <div className="h-48 flex items-center justify-center text-gray-500">
                  Not enough data for lifecycle chart
                </div>
              )}
            </CardContent>
          </Card>

          {/* Prevalence Over Time */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <TrendingUp className="h-4 w-4" />
                Prevalence Over Time
              </CardTitle>
            </CardHeader>
            <CardContent>
              {narrative.prevalence_history.length > 0 ? (
                <PrevalenceChart data={narrative.prevalence_history} height={250} />
              ) : (
                <div className="h-48 flex items-center justify-center text-gray-500">
                  Not enough data for prevalence chart
                </div>
              )}
            </CardContent>
          </Card>

          {/* Claims */}
          <Tabs defaultValue="supporting">
            <TabsList>
              <TabsTrigger value="supporting">
                <CheckCircle className="h-4 w-4 mr-2 text-green-600" />
                Supporting ({narrative.supporting_claims.length})
              </TabsTrigger>
              <TabsTrigger value="contradicting">
                <XCircle className="h-4 w-4 mr-2 text-red-600" />
                Contradicting ({narrative.contradicting_claims.length})
              </TabsTrigger>
            </TabsList>

            <TabsContent value="supporting" className="mt-4">
              {narrative.supporting_claims.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center text-gray-500">
                    No supporting claims identified
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-3">
                  {narrative.supporting_claims.map((claim) => (
                    <ClaimCard key={claim.id} claim={claim} type="supporting" />
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="contradicting" className="mt-4">
              {narrative.contradicting_claims.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center text-gray-500">
                    No contradicting claims identified
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-3">
                  {narrative.contradicting_claims.map((claim) => (
                    <ClaimCard key={claim.id} claim={claim} type="contradicting" />
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>

          {/* Supporting Items */}
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Supporting Items</CardTitle>
                <span className="text-sm text-gray-500">
                  {items?.total ?? 0} items
                </span>
              </div>
            </CardHeader>
            <CardContent>
              {itemsLoading ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-32 skeleton rounded-xl" />
                  ))}
                </div>
              ) : items?.items.length === 0 ? (
                <div className="py-8 text-center text-gray-500">
                  No items found
                </div>
              ) : (
                <div className="space-y-4">
                  {items?.items.map((item) => (
                    <ItemCard key={item.id} item={item} />
                  ))}
                  {items && items.total > items.page_size && (
                    <div className="flex items-center justify-center gap-2 pt-4">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setItemsPage((p) => Math.max(1, p - 1))}
                        disabled={itemsPage <= 1}
                      >
                        Previous
                      </Button>
                      <span className="text-sm text-gray-500">
                        Page {itemsPage} of{" "}
                        {Math.ceil(items.total / items.page_size)}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setItemsPage((p) => p + 1)}
                        disabled={!items.has_more}
                      >
                        Next
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right Column */}
        <div className="space-y-6">
          {/* Sentiment Breakdown */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Sentiment Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <SentimentBar
                  label="Positive"
                  value={narrative.sentiment_breakdown.positive}
                  total={sentimentTotal}
                  color="bg-green-500"
                />
                <SentimentBar
                  label="Neutral"
                  value={narrative.sentiment_breakdown.neutral}
                  total={sentimentTotal}
                  color="bg-gray-400"
                />
                <SentimentBar
                  label="Mixed"
                  value={narrative.sentiment_breakdown.mixed}
                  total={sentimentTotal}
                  color="bg-amber-500"
                />
                <SentimentBar
                  label="Negative"
                  value={narrative.sentiment_breakdown.negative}
                  total={sentimentTotal}
                  color="bg-red-500"
                />
              </div>
            </CardContent>
          </Card>

          {/* Top Amplifiers */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Top Amplifiers</CardTitle>
            </CardHeader>
            <CardContent>
              {narrative.amplifiers.length === 0 ? (
                <p className="text-sm text-gray-500">No amplifiers identified</p>
              ) : (
                <div className="space-y-3">
                  {narrative.amplifiers.slice(0, 10).map((amp) => (
                    <div
                      key={amp.entity_id}
                      className="flex items-center justify-between"
                    >
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {amp.entity_name}
                        </p>
                        <p className="text-xs text-gray-500 capitalize">
                          {amp.entity_type} - {amp.item_count} mentions
                        </p>
                      </div>
                      <Badge variant="outline">
                        {Math.round(amp.amplification_score * 100)}%
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Origin Item */}
          {narrative.origin_item && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Origin</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <h4 className="text-sm font-medium text-gray-900">
                    {narrative.origin_item.title}
                  </h4>
                  <p className="text-sm text-gray-500">
                    {narrative.origin_item.source.name}
                  </p>
                  <p className="text-xs text-gray-400">
                    {formatDate(narrative.origin_item.published_at)}
                  </p>
                  {narrative.origin_item.url && (
                    <a
                      href={narrative.origin_item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-sm text-lantern-600 hover:text-lantern-700"
                    >
                      View source
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// Sub-components

function SentimentBar({
  label,
  value,
  total,
  color,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
}) {
  const percentage = total > 0 ? (value / total) * 100 : 0;

  return (
    <div>
      <div className="flex items-center justify-between text-sm mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="text-gray-900 font-medium">
          {value} ({percentage.toFixed(1)}%)
        </span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function ClaimCard({ claim, type }: { claim: Claim; type: "supporting" | "contradicting" }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full",
              type === "supporting"
                ? "bg-green-100 text-green-600"
                : "bg-red-100 text-red-600"
            )}
          >
            {type === "supporting" ? (
              <CheckCircle className="h-4 w-4" />
            ) : (
              <XCircle className="h-4 w-4" />
            )}
          </div>
          <div className="flex-1">
            <p className="text-sm text-gray-900">{claim.text}</p>
            <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
              {claim.speaker && <span>By: {claim.speaker}</span>}
              <span>Confidence: {Math.round(claim.confidence * 100)}%</span>
              <Badge variant="outline" className="text-xs capitalize">
                {claim.type}
              </Badge>
              {claim.verified !== undefined && (
                <Badge
                  variant={claim.verified ? "success" : "warning"}
                  className="text-xs"
                >
                  {claim.verified ? "Verified" : "Unverified"}
                </Badge>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
