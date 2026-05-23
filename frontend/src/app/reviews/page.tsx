"use client";

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardCheck,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  MessageSquare,
  FileText,
  User,
  Filter,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
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
  DialogFooter,
} from "@/components/ui/Modal";
import { getReviewItems, getReviewItem, submitReview } from "@/lib/api";
import { formatRelativeTime, getPriorityColor, getStatusColor, cn } from "@/lib/utils";
import { ReviewItem, ReviewStatus, ReviewAction } from "@/types";

const statusLabels: Record<ReviewStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
};

const typeLabels: Record<string, string> = {
  narrative: "Narrative",
  claim: "Claim",
  artifact: "Artifact",
  entity: "Entity",
};

const typeIcons: Record<string, React.ReactNode> = {
  narrative: <MessageSquare className="h-4 w-4" />,
  claim: <FileText className="h-4 w-4" />,
  artifact: <FileText className="h-4 w-4" />,
  entity: <User className="h-4 w-4" />,
};

export default function ReviewsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<string>("pending");
  const [selectedReview, setSelectedReview] = useState<ReviewItem | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [priorityFilter, setPriorityFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const { data: reviews, isLoading } = useQuery({
    queryKey: ["reviews", activeTab],
    queryFn: () =>
      getReviewItems(activeTab === "all" ? undefined : activeTab, 1, 50),
  });

  const { data: reviewDetail, isLoading: detailLoading } = useQuery({
    queryKey: ["review", selectedReview?.id],
    queryFn: () => getReviewItem(selectedReview!.id),
    enabled: !!selectedReview,
  });

  const reviewMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: ReviewAction }) =>
      submitReview(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      setSelectedReview(null);
      setReviewNotes("");
    },
  });

  const handleApprove = () => {
    if (!selectedReview) return;
    reviewMutation.mutate({
      id: selectedReview.id,
      action: { action: "approve", notes: reviewNotes || undefined },
    });
  };

  const handleReject = () => {
    if (!selectedReview) return;
    reviewMutation.mutate({
      id: selectedReview.id,
      action: { action: "reject", notes: reviewNotes || undefined },
    });
  };

  const filteredReviews =
    reviews?.items.filter((review) => {
      const matchesPriority =
        priorityFilter === "all" || review.priority === priorityFilter;
      const matchesType = typeFilter === "all" || review.type === typeFilter;
      return matchesPriority && matchesType;
    }) ?? [];

  const pendingCount =
    reviews?.items.filter((r) => r.status === "pending").length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Review Queue</h1>
          <p className="text-gray-500 mt-1">
            Review and approve AI-generated content
          </p>
        </div>
        {pendingCount > 0 && (
          <Badge variant="warning" className="text-sm">
            {pendingCount} pending review{pendingCount !== 1 ? "s" : ""}
          </Badge>
        )}
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Priority
              </label>
              <Select value={priorityFilter} onValueChange={setPriorityFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="All priorities" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Priorities</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Type
              </label>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="narrative">Narrative</SelectItem>
                  <SelectItem value="claim">Claim</SelectItem>
                  <SelectItem value="artifact">Artifact</SelectItem>
                  <SelectItem value="entity">Entity</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="pending">
            <Clock className="h-4 w-4 mr-2" />
            Pending
          </TabsTrigger>
          <TabsTrigger value="approved">
            <CheckCircle className="h-4 w-4 mr-2" />
            Approved
          </TabsTrigger>
          <TabsTrigger value="rejected">
            <XCircle className="h-4 w-4 mr-2" />
            Rejected
          </TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-4">
          {isLoading ? (
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-24 skeleton rounded-xl" />
              ))}
            </div>
          ) : filteredReviews.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <ClipboardCheck className="h-12 w-12 text-gray-300 mx-auto" />
                <p className="mt-4 text-gray-900 font-medium">
                  No items to review
                </p>
                <p className="text-sm text-gray-500">
                  {activeTab === "pending"
                    ? "All caught up! No pending reviews."
                    : "No items match your filters."}
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {filteredReviews.map((review) => (
                <ReviewCard
                  key={review.id}
                  review={review}
                  onClick={() => setSelectedReview(review)}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Review Detail Dialog */}
      <Dialog
        open={!!selectedReview}
        onOpenChange={() => {
          setSelectedReview(null);
          setReviewNotes("");
        }}
      >
        <DialogContent className="max-w-2xl">
          {detailLoading ? (
            <div className="space-y-4">
              <div className="h-8 w-48 skeleton" />
              <div className="h-32 skeleton" />
            </div>
          ) : reviewDetail ? (
            <>
              <DialogHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <DialogTitle className="flex items-center gap-2">
                      {typeIcons[reviewDetail.type]}
                      Review {typeLabels[reviewDetail.type]}
                    </DialogTitle>
                    <div className="flex items-center gap-2 mt-2">
                      <Badge className={getStatusColor(reviewDetail.status)}>
                        {statusLabels[reviewDetail.status]}
                      </Badge>
                      <Badge className={getPriorityColor(reviewDetail.priority)}>
                        {reviewDetail.priority}
                      </Badge>
                    </div>
                  </div>
                </div>
              </DialogHeader>

              <div className="space-y-4 py-4">
                {/* Reason */}
                <div>
                  <h4 className="text-sm font-medium text-gray-900 mb-1">
                    Reason for Review
                  </h4>
                  <p className="text-sm text-gray-600">{reviewDetail.reason}</p>
                </div>

                {/* Content */}
                <div>
                  <h4 className="text-sm font-medium text-gray-900 mb-2">
                    Content
                  </h4>
                  <Card>
                    <CardContent className="p-4">
                      <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 p-3 rounded-lg">
                        {JSON.stringify(reviewDetail.data, null, 2)}
                      </pre>
                    </CardContent>
                  </Card>
                </div>

                {/* Notes */}
                {reviewDetail.status === "pending" && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Notes (optional)
                    </label>
                    <textarea
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                      placeholder="Add notes about your decision..."
                      className="w-full h-20 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lantern-500 focus:border-transparent resize-none"
                    />
                  </div>
                )}

                {/* Previous Notes */}
                {reviewDetail.notes && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-900 mb-1">
                      Review Notes
                    </h4>
                    <p className="text-sm text-gray-600 bg-gray-50 p-3 rounded-lg">
                      {reviewDetail.notes}
                    </p>
                  </div>
                )}

                {/* Meta */}
                <div className="text-sm text-gray-500 space-y-1">
                  <p>Created: {formatRelativeTime(reviewDetail.created_at)}</p>
                  {reviewDetail.reviewed_by && (
                    <p>Reviewed by: {reviewDetail.reviewed_by}</p>
                  )}
                  {reviewDetail.reviewed_at && (
                    <p>Reviewed: {formatRelativeTime(reviewDetail.reviewed_at)}</p>
                  )}
                </div>
              </div>

              {reviewDetail.status === "pending" && (
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setSelectedReview(null);
                      setReviewNotes("");
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={handleReject}
                    disabled={reviewMutation.isPending}
                    loading={reviewMutation.isPending}
                  >
                    <XCircle className="h-4 w-4 mr-2" />
                    Reject
                  </Button>
                  <Button
                    onClick={handleApprove}
                    disabled={reviewMutation.isPending}
                    loading={reviewMutation.isPending}
                  >
                    <CheckCircle className="h-4 w-4 mr-2" />
                    Approve
                  </Button>
                </DialogFooter>
              )}
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReviewCard({
  review,
  onClick,
}: {
  review: ReviewItem;
  onClick: () => void;
}) {
  return (
    <Card
      className="cursor-pointer hover:shadow-medium transition-shadow"
      onClick={onClick}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3">
            <div
              className={cn(
                "flex h-10 w-10 items-center justify-center rounded-lg",
                review.status === "pending"
                  ? "bg-amber-100 text-amber-700"
                  : review.status === "approved"
                  ? "bg-green-100 text-green-700"
                  : "bg-red-100 text-red-700"
              )}
            >
              {typeIcons[review.type]}
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-medium text-gray-900">
                  {typeLabels[review.type]}
                </h3>
                <Badge className={getStatusColor(review.status)}>
                  {statusLabels[review.status]}
                </Badge>
                <Badge className={getPriorityColor(review.priority)}>
                  {review.priority}
                </Badge>
              </div>
              <p className="text-sm text-gray-500 line-clamp-2">
                {review.reason}
              </p>
            </div>
          </div>
          <span className="text-xs text-gray-400 flex-shrink-0">
            {formatRelativeTime(review.created_at)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
