"use client";

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  Plus,
  Clock,
  CheckCircle,
  XCircle,
  Send,
  Eye,
  Edit,
  Trash,
  FileEdit,
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
  DialogDescription,
  DialogFooter,
} from "@/components/ui/Modal";
import { CitedText } from "@/components/domain/CitationPopover";
import { ItemCard } from "@/components/domain/ItemCard";
import {
  getArtifacts,
  getArtifact,
  createArtifact,
  submitArtifactForReview,
  getSubjects,
} from "@/lib/api";
import { formatRelativeTime, getStatusColor, cn } from "@/lib/utils";
import { Artifact, ArtifactType, ArtifactRequest, ArtifactStatus } from "@/types";

const artifactTypeLabels: Record<ArtifactType, string> = {
  brief: "Brief",
  report: "Report",
  analysis: "Analysis",
  summary: "Summary",
  timeline: "Timeline",
  comparison: "Comparison",
};

const statusLabels: Record<ArtifactStatus, string> = {
  draft: "Draft",
  pending_review: "Pending Review",
  approved: "Approved",
  rejected: "Rejected",
};

export default function ArtifactsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<string>("all");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [newArtifact, setNewArtifact] = useState<ArtifactRequest>({
    type: "brief",
    title: "",
    subject_id: "",
    instructions: "",
  });

  const { data: subjects } = useQuery({
    queryKey: ["subjects-list"],
    queryFn: () => getSubjects(1, 100),
  });

  const { data: artifacts, isLoading } = useQuery({
    queryKey: ["artifacts", activeTab],
    queryFn: () =>
      getArtifacts(activeTab === "all" ? undefined : activeTab, 1, 50),
  });

  const { data: artifactDetail, isLoading: detailLoading } = useQuery({
    queryKey: ["artifact", selectedArtifact?.id],
    queryFn: () => getArtifact(selectedArtifact!.id),
    enabled: !!selectedArtifact,
  });

  const createMutation = useMutation({
    mutationFn: createArtifact,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artifacts"] });
      setIsCreateOpen(false);
      setNewArtifact({
        type: "brief",
        title: "",
        subject_id: "",
        instructions: "",
      });
    },
  });

  const submitMutation = useMutation({
    mutationFn: (id: string) => submitArtifactForReview(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artifacts"] });
      queryClient.invalidateQueries({ queryKey: ["artifact", selectedArtifact?.id] });
    },
  });

  const handleCreate = () => {
    createMutation.mutate(newArtifact);
  };

  const handleSubmitForReview = (id: string) => {
    submitMutation.mutate(id);
  };

  const getStatusIcon = (status: ArtifactStatus) => {
    switch (status) {
      case "draft":
        return <FileEdit className="h-4 w-4" />;
      case "pending_review":
        return <Clock className="h-4 w-4" />;
      case "approved":
        return <CheckCircle className="h-4 w-4" />;
      case "rejected":
        return <XCircle className="h-4 w-4" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Artifacts</h1>
          <p className="text-gray-500 mt-1">
            Create and manage briefs, reports, and analyses
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          New Artifact
        </Button>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="draft">Drafts</TabsTrigger>
          <TabsTrigger value="pending_review">Pending Review</TabsTrigger>
          <TabsTrigger value="approved">Approved</TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-4">
          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="h-40 skeleton rounded-xl" />
              ))}
            </div>
          ) : artifacts?.items.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <FileText className="h-12 w-12 text-gray-300 mx-auto" />
                <p className="mt-4 text-gray-900 font-medium">
                  No artifacts found
                </p>
                <p className="text-sm text-gray-500">
                  {activeTab === "all"
                    ? "Create your first artifact to get started"
                    : `No ${statusLabels[activeTab as ArtifactStatus]?.toLowerCase()} artifacts`}
                </p>
                {activeTab === "all" && (
                  <Button className="mt-4" onClick={() => setIsCreateOpen(true)}>
                    <Plus className="h-4 w-4 mr-2" />
                    Create Artifact
                  </Button>
                )}
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {artifacts?.items.map((artifact) => (
                <ArtifactCard
                  key={artifact.id}
                  artifact={artifact}
                  onClick={() => setSelectedArtifact(artifact)}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Create Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Request New Artifact</DialogTitle>
            <DialogDescription>
              Describe what you want to create and our AI will draft it for you
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Title
              </label>
              <Input
                value={newArtifact.title}
                onChange={(e) =>
                  setNewArtifact({ ...newArtifact, title: e.target.value })
                }
                placeholder="e.g., Q4 Market Analysis Brief"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Type
              </label>
              <Select
                value={newArtifact.type}
                onValueChange={(value) =>
                  setNewArtifact({
                    ...newArtifact,
                    type: value as ArtifactType,
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="brief">Brief</SelectItem>
                  <SelectItem value="report">Report</SelectItem>
                  <SelectItem value="analysis">Analysis</SelectItem>
                  <SelectItem value="summary">Summary</SelectItem>
                  <SelectItem value="timeline">Timeline</SelectItem>
                  <SelectItem value="comparison">Comparison</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Subject
              </label>
              <Select
                value={newArtifact.subject_id}
                onValueChange={(value) =>
                  setNewArtifact({ ...newArtifact, subject_id: value })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select subject" />
                </SelectTrigger>
                <SelectContent>
                  {subjects?.items.map((subject) => (
                    <SelectItem key={subject.id} value={subject.id}>
                      {subject.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Instructions
              </label>
              <textarea
                value={newArtifact.instructions}
                onChange={(e) =>
                  setNewArtifact({ ...newArtifact, instructions: e.target.value })
                }
                placeholder="Describe what you want this artifact to cover..."
                className="w-full h-24 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lantern-500 focus:border-transparent resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                !newArtifact.title.trim() ||
                !newArtifact.subject_id ||
                !newArtifact.instructions.trim() ||
                createMutation.isPending
              }
              loading={createMutation.isPending}
            >
              Create Artifact
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Detail/Review Dialog */}
      <Dialog
        open={!!selectedArtifact}
        onOpenChange={() => setSelectedArtifact(null)}
      >
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          {detailLoading ? (
            <div className="space-y-4">
              <div className="h-8 w-48 skeleton" />
              <div className="h-64 skeleton" />
            </div>
          ) : artifactDetail ? (
            <>
              <DialogHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <DialogTitle>{artifactDetail.title}</DialogTitle>
                    <div className="flex items-center gap-2 mt-2">
                      <Badge className={getStatusColor(artifactDetail.status)}>
                        {getStatusIcon(artifactDetail.status)}
                        <span className="ml-1">
                          {statusLabels[artifactDetail.status]}
                        </span>
                      </Badge>
                      <Badge variant="outline">
                        {artifactTypeLabels[artifactDetail.type]}
                      </Badge>
                      <span className="text-sm text-gray-500">
                        v{artifactDetail.version}
                      </span>
                    </div>
                  </div>
                  {artifactDetail.status === "draft" && (
                    <Button
                      size="sm"
                      onClick={() => handleSubmitForReview(artifactDetail.id)}
                      loading={submitMutation.isPending}
                    >
                      <Send className="h-4 w-4 mr-2" />
                      Submit for Review
                    </Button>
                  )}
                </div>
              </DialogHeader>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-4">
                {/* Content */}
                <div className="lg:col-span-2">
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">Content</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="prose prose-sm max-w-none">
                        <CitedText
                          text={artifactDetail.content}
                          citations={artifactDetail.citations}
                        />
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Sources Panel */}
                <div className="space-y-4">
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">
                        Sources ({artifactDetail.citations.length})
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {artifactDetail.citations.length === 0 ? (
                        <p className="text-sm text-gray-500">No citations</p>
                      ) : (
                        <div className="space-y-3 max-h-96 overflow-y-auto">
                          {artifactDetail.citations.map((citation, i) => (
                            <div
                              key={citation.id}
                              className="p-3 bg-gray-50 rounded-lg"
                            >
                              <p className="text-xs text-gray-500 mb-1">
                                [{i + 1}]
                              </p>
                              <p className="text-sm text-gray-700 italic">
                                &ldquo;{citation.text}&rdquo;
                              </p>
                              {citation.item && (
                                <p className="text-xs text-gray-500 mt-2">
                                  {citation.item.source.name} -{" "}
                                  {formatRelativeTime(
                                    citation.item.published_at
                                  )}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">Details</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-500">Created</span>
                        <span className="text-gray-900">
                          {formatRelativeTime(artifactDetail.created_at)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Updated</span>
                        <span className="text-gray-900">
                          {formatRelativeTime(artifactDetail.updated_at)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Created by</span>
                        <span className="text-gray-900">
                          {artifactDetail.created_by}
                        </span>
                      </div>
                      {artifactDetail.reviewed_by && (
                        <div className="flex justify-between">
                          <span className="text-gray-500">Reviewed by</span>
                          <span className="text-gray-900">
                            {artifactDetail.reviewed_by}
                          </span>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ArtifactCard({
  artifact,
  onClick,
}: {
  artifact: Artifact;
  onClick: () => void;
}) {
  const getStatusIcon = (status: ArtifactStatus) => {
    switch (status) {
      case "draft":
        return <FileEdit className="h-4 w-4" />;
      case "pending_review":
        return <Clock className="h-4 w-4" />;
      case "approved":
        return <CheckCircle className="h-4 w-4" />;
      case "rejected":
        return <XCircle className="h-4 w-4" />;
    }
  };

  return (
    <Card
      className="cursor-pointer hover:shadow-medium transition-shadow"
      onClick={onClick}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
            <FileText className="h-5 w-5" />
          </div>
          <Badge className={getStatusColor(artifact.status)}>
            {getStatusIcon(artifact.status)}
            <span className="ml-1">{statusLabels[artifact.status]}</span>
          </Badge>
        </div>

        <h3 className="font-medium text-gray-900 line-clamp-2 mb-1">
          {artifact.title}
        </h3>

        <div className="flex items-center gap-2 mb-3">
          <Badge variant="outline" className="text-xs">
            {artifactTypeLabels[artifact.type]}
          </Badge>
          <span className="text-xs text-gray-500">v{artifact.version}</span>
        </div>

        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>{artifact.citations.length} citations</span>
          <span>{formatRelativeTime(artifact.updated_at)}</span>
        </div>
      </CardContent>
    </Card>
  );
}
