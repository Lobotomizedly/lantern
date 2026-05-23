"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Users,
  Plus,
  Search,
  Filter,
  ArrowRight,
  Building,
  User,
  Tag,
  Calendar,
  Package,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
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
import { getSubjects, createSubject } from "@/lib/api";
import { formatRelativeTime, cn } from "@/lib/utils";
import { Subject } from "@/types";

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

export default function SubjectsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newSubject, setNewSubject] = useState({
    name: "",
    type: "organization" as Subject["type"],
    description: "",
  });

  const { data: subjects, isLoading, refetch } = useQuery({
    queryKey: ["subjects", page],
    queryFn: () => getSubjects(page, 20),
  });

  const filteredSubjects =
    subjects?.items.filter((subject) => {
      const matchesSearch =
        searchQuery === "" ||
        subject.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        subject.description?.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesType =
        typeFilter === "all" || subject.type === typeFilter;
      return matchesSearch && matchesType;
    }) ?? [];

  const handleCreateSubject = async () => {
    try {
      await createSubject(newSubject);
      setIsCreateOpen(false);
      setNewSubject({ name: "", type: "organization", description: "" });
      refetch();
    } catch (error) {
      console.error("Failed to create subject:", error);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Subjects</h1>
          <p className="text-gray-500 mt-1">
            Manage the entities you are tracking for narrative intelligence
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          New Subject
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="flex-1">
          <Input
            placeholder="Search subjects..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            icon={<Search className="h-4 w-4" />}
          />
        </div>
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-full sm:w-48">
            <Filter className="h-4 w-4 mr-2" />
            <SelectValue placeholder="Filter by type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="person">Person</SelectItem>
            <SelectItem value="organization">Organization</SelectItem>
            <SelectItem value="topic">Topic</SelectItem>
            <SelectItem value="event">Event</SelectItem>
            <SelectItem value="product">Product</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Subjects Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-40 skeleton rounded-xl" />
          ))}
        </div>
      ) : filteredSubjects.length === 0 ? (
        <Card>
          <CardContent className="py-12">
            <div className="text-center">
              <Users className="h-12 w-12 text-gray-300 mx-auto" />
              <p className="mt-4 text-gray-900 font-medium">No subjects found</p>
              <p className="text-sm text-gray-500">
                {searchQuery || typeFilter !== "all"
                  ? "Try adjusting your search or filters"
                  : "Create your first subject to get started"}
              </p>
              {!searchQuery && typeFilter === "all" && (
                <Button
                  className="mt-4"
                  onClick={() => setIsCreateOpen(true)}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Create Subject
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSubjects.map((subject) => (
            <SubjectCard key={subject.id} subject={subject} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {subjects && subjects.total > subjects.page_size && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            Previous
          </Button>
          <span className="text-sm text-gray-500">
            Page {page} of {Math.ceil(subjects.total / subjects.page_size)}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => p + 1)}
            disabled={!subjects.has_more}
          >
            Next
          </Button>
        </div>
      )}

      {/* Create Subject Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Subject</DialogTitle>
            <DialogDescription>
              Add a new entity to track for narrative intelligence
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name
              </label>
              <Input
                value={newSubject.name}
                onChange={(e) =>
                  setNewSubject({ ...newSubject, name: e.target.value })
                }
                placeholder="Enter subject name"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Type
              </label>
              <Select
                value={newSubject.type}
                onValueChange={(value) =>
                  setNewSubject({
                    ...newSubject,
                    type: value as Subject["type"],
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="person">Person</SelectItem>
                  <SelectItem value="organization">Organization</SelectItem>
                  <SelectItem value="topic">Topic</SelectItem>
                  <SelectItem value="event">Event</SelectItem>
                  <SelectItem value="product">Product</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description (optional)
              </label>
              <Input
                value={newSubject.description}
                onChange={(e) =>
                  setNewSubject({ ...newSubject, description: e.target.value })
                }
                placeholder="Brief description"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateSubject}
              disabled={!newSubject.name.trim()}
            >
              Create Subject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SubjectCard({ subject }: { subject: Subject }) {
  const Icon = subjectTypeIcons[subject.type] || Users;

  return (
    <Link href={`/subjects/${subject.id}`}>
      <Card className="h-full hover:shadow-medium hover:border-lantern-300 transition-all cursor-pointer">
        <CardContent className="p-5">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
                <Icon className="h-6 w-6" />
              </div>
              <div>
                <h3 className="font-semibold text-gray-900">{subject.name}</h3>
                <Badge variant="secondary" className="mt-1 capitalize">
                  {subject.type}
                </Badge>
              </div>
            </div>
            <ArrowRight className="h-5 w-5 text-gray-400" />
          </div>

          {subject.description && (
            <p className="mt-3 text-sm text-gray-500 line-clamp-2">
              {subject.description}
            </p>
          )}

          {subject.aliases.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {subject.aliases.slice(0, 3).map((alias, i) => (
                <Badge key={i} variant="outline" className="text-xs">
                  {alias}
                </Badge>
              ))}
              {subject.aliases.length > 3 && (
                <Badge variant="outline" className="text-xs">
                  +{subject.aliases.length - 3}
                </Badge>
              )}
            </div>
          )}

          <div className="mt-4 pt-3 border-t border-gray-100 text-xs text-gray-400">
            Updated {formatRelativeTime(subject.updated_at)}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
