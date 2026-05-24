"use client";

import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Users,
  FileText,
  MessageSquare,
  Bot,
  ClipboardCheck,
  TrendingUp,
  ArrowRight,
  Activity,
  Clock,
  AlertCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { getDashboardStats, getRecentActivity, getSubjects } from "@/lib/api";
import { formatRelativeTime, cn } from "@/lib/utils";
import { RecentActivity, Subject } from "@/types";

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: getDashboardStats,
    retry: false,
  });

  const { data: activity, isLoading: activityLoading } = useQuery({
    queryKey: ["recent-activity"],
    queryFn: () => getRecentActivity(10),
    retry: false,
  });

  const { data: subjectsData, isLoading: subjectsLoading } = useQuery({
    queryKey: ["subjects-preview"],
    queryFn: () => getSubjects(1, 5),
    retry: false,
  });

  // If not authenticated, redirect to login
  if (statsError) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">
            Welcome back. Here is what is happening with your narratives.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/subjects">
            <Button variant="outline">
              <Users className="h-4 w-4 mr-2" />
              View Subjects
            </Button>
          </Link>
          <Link href="/search">
            <Button>
              <TrendingUp className="h-4 w-4 mr-2" />
              Explore
            </Button>
          </Link>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          title="Subjects"
          value={stats?.subjects?.total ?? 0}
          icon={Users}
          loading={statsLoading}
          href="/subjects"
        />
        <StatCard
          title="Items"
          value={stats?.items?.total ?? 0}
          icon={FileText}
          loading={statsLoading}
          subtitle={`+${stats?.items?.new_today ?? 0} today`}
        />
        <StatCard
          title="Narratives"
          value={stats?.narratives?.total ?? 0}
          icon={MessageSquare}
          loading={statsLoading}
          href="/search?type=narrative"
        />
        <StatCard
          title="Active Agents"
          value={stats?.agents?.running ?? 0}
          icon={Bot}
          loading={statsLoading}
          href="/agents"
        />
        <StatCard
          title="Events"
          value={stats?.events?.total ?? 0}
          icon={ClipboardCheck}
          loading={statsLoading}
          href="/timeline"
          highlight={stats?.events?.new_today ? stats.events.new_today > 0 : false}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Subjects List */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-base">Your Subjects</CardTitle>
            <Link href="/subjects">
              <Button variant="ghost" size="sm">
                View all
                <ArrowRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
          </CardHeader>
          <CardContent>
            {subjectsLoading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-16 skeleton rounded-lg" />
                ))}
              </div>
            ) : subjectsData?.items.length === 0 ? (
              <div className="text-center py-8">
                <Users className="h-12 w-12 text-gray-300 mx-auto" />
                <p className="mt-4 text-gray-900 font-medium">No subjects yet</p>
                <p className="text-sm text-gray-500">
                  Create your first subject to start tracking narratives
                </p>
                <Link href="/subjects/new">
                  <Button className="mt-4" size="sm">
                    Create Subject
                  </Button>
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {subjectsData?.items.map((subject) => (
                  <SubjectRow key={subject.id} subject={subject} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Activity */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Recent Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            {activityLoading ? (
              <div className="space-y-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="h-12 skeleton rounded-lg" />
                ))}
              </div>
            ) : activity?.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                No recent activity
              </div>
            ) : (
              <div className="space-y-3">
                {activity?.map((item) => (
                  <ActivityItem key={item.id} activity={item} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Quick Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Link href="/search">
              <QuickActionCard
                title="Search Content"
                description="Find items, narratives, and events"
                icon={TrendingUp}
              />
            </Link>
            <Link href="/timeline">
              <QuickActionCard
                title="View Timeline"
                description="Explore events chronologically"
                icon={Clock}
              />
            </Link>
            <Link href="/artifacts">
              <QuickActionCard
                title="Create Artifact"
                description="Draft reports and briefs"
                icon={FileText}
              />
            </Link>
            <Link href="/agents">
              <QuickActionCard
                title="Launch Agent"
                description="Start an investigator or monitor"
                icon={Bot}
              />
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// Sub-components

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  loading?: boolean;
  subtitle?: string;
  href?: string;
  highlight?: boolean;
}

function StatCard({
  title,
  value,
  icon: Icon,
  loading,
  subtitle,
  href,
  highlight,
}: StatCardProps) {
  const content = (
    <Card
      className={cn(
        "transition-colors",
        href && "hover:border-lantern-300 cursor-pointer",
        highlight && "border-amber-300 bg-amber-50"
      )}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500">{title}</p>
            {loading ? (
              <div className="h-8 w-16 skeleton mt-1" />
            ) : (
              <p className="text-2xl font-semibold text-gray-900">{value}</p>
            )}
            {subtitle && (
              <p className="text-xs text-gray-500 mt-1">{subtitle}</p>
            )}
          </div>
          <div
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-lg",
              highlight ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-600"
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );

  if (href) {
    return <Link href={href}>{content}</Link>;
  }

  return content;
}

function SubjectRow({ subject }: { subject: Subject }) {
  return (
    <Link href={`/subjects/${subject.id}`}>
      <div className="flex items-center justify-between p-3 rounded-lg border border-gray-200 hover:border-lantern-300 hover:bg-gray-50 transition-colors cursor-pointer">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
            <Users className="h-5 w-5" />
          </div>
          <div>
            <p className="font-medium text-gray-900">{subject.name}</p>
            <p className="text-sm text-gray-500 capitalize">{subject.type}</p>
          </div>
        </div>
        <ArrowRight className="h-4 w-4 text-gray-400" />
      </div>
    </Link>
  );
}

function ActivityItem({ activity }: { activity: RecentActivity }) {
  const getActivityIcon = () => {
    switch (activity.type) {
      case "item":
        return FileText;
      case "narrative":
        return MessageSquare;
      case "event":
        return Clock;
      case "artifact":
        return FileText;
      case "agent":
        return Bot;
      default:
        return Activity;
    }
  };

  const Icon = getActivityIcon();
  const source = activity.metadata?.source as string | undefined;

  return (
    <div className="flex items-start gap-3 p-2 rounded-lg hover:bg-gray-50 transition-colors">
      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
        <Icon className="h-4 w-4 text-gray-600" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-900 truncate">{activity.title}</p>
        <p className="text-xs text-gray-500">
          {source && (
            <span className="font-medium">{source} - </span>
          )}
          {formatRelativeTime(activity.timestamp)}
        </p>
      </div>
    </div>
  );
}

interface QuickActionCardProps {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}

function QuickActionCard({ title, description, icon: Icon }: QuickActionCardProps) {
  return (
    <div className="flex items-center gap-4 p-4 rounded-lg border border-gray-200 hover:border-lantern-300 hover:bg-gray-50 transition-colors cursor-pointer">
      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <p className="font-medium text-gray-900">{title}</p>
        <p className="text-sm text-gray-500">{description}</p>
      </div>
    </div>
  );
}
