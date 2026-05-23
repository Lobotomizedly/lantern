"use client";

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Play,
  Pause,
  RefreshCw,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Terminal,
  DollarSign,
  ChevronRight,
  Plus,
  Search,
  Calendar,
  FileText,
  Eye,
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
import {
  getAgents,
  getAgentRuns,
  runAgent,
  spawnInvestigator,
  getSubjects,
} from "@/lib/api";
import { formatRelativeTime, formatCurrency, getStatusColor, cn } from "@/lib/utils";
import {
  Agent,
  AgentRun,
  AgentStatus,
  AgentType,
  AgentTrace,
  InvestigatorRequest,
} from "@/types";
import { useAgentWatchStore } from "@/lib/store";

const agentTypeLabels: Record<AgentType, string> = {
  digest: "Digest Agent",
  monitor: "Monitor Agent",
  investigator: "Investigator",
  artifact_drafter: "Artifact Drafter",
};

const agentTypeIcons: Record<AgentType, React.ReactNode> = {
  digest: <Calendar className="h-4 w-4" />,
  monitor: <Eye className="h-4 w-4" />,
  investigator: <Search className="h-4 w-4" />,
  artifact_drafter: <FileText className="h-4 w-4" />,
};

const statusIcons: Record<AgentStatus, React.ReactNode> = {
  scheduled: <Clock className="h-4 w-4" />,
  running: <RefreshCw className="h-4 w-4 animate-spin" />,
  completed: <CheckCircle className="h-4 w-4" />,
  failed: <XCircle className="h-4 w-4" />,
  cancelled: <AlertCircle className="h-4 w-4" />,
};

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const { watchedRuns, addWatchedRun, removeWatchedRun } = useAgentWatchStore();
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [selectedRun, setSelectedRun] = useState<AgentRun | null>(null);
  const [isInvestigatorOpen, setIsInvestigatorOpen] = useState(false);
  const [investigatorRequest, setInvestigatorRequest] = useState<InvestigatorRequest>({
    subject_id: "",
    question: "",
    depth: "medium",
  });

  const { data: subjects } = useQuery({
    queryKey: ["subjects-list"],
    queryFn: () => getSubjects(1, 100),
  });

  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: () => getAgents(1, 50),
  });

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ["agent-runs", selectedAgent?.id],
    queryFn: () => getAgentRuns(selectedAgent!.id, 1, 20),
    enabled: !!selectedAgent,
  });

  const runMutation = useMutation({
    mutationFn: (agentId: string) => runAgent(agentId),
    onSuccess: (run, agentId) => {
      const agent = agents?.items.find((a) => a.id === agentId);
      if (agent) {
        addWatchedRun({
          agentId,
          runId: run.id,
          agentName: agent.name,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-runs", agentId] });
    },
  });

  const investigatorMutation = useMutation({
    mutationFn: spawnInvestigator,
    onSuccess: (run) => {
      addWatchedRun({
        agentId: "investigator",
        runId: run.id,
        agentName: "Investigator",
      });
      setIsInvestigatorOpen(false);
      setInvestigatorRequest({
        subject_id: "",
        question: "",
        depth: "medium",
      });
    },
  });

  const standingAgents = agents?.items.filter((a) => a.schedule) ?? [];
  const adhocAgents = agents?.items.filter((a) => !a.schedule) ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Agent Console</h1>
          <p className="text-gray-500 mt-1">
            Manage and monitor your AI agents
          </p>
        </div>
        <Button onClick={() => setIsInvestigatorOpen(true)}>
          <Search className="h-4 w-4 mr-2" />
          Spawn Investigator
        </Button>
      </div>

      {/* Watched Runs */}
      {watchedRuns.length > 0 && (
        <Card className="border-lantern-200 bg-lantern-50">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Eye className="h-4 w-4" />
              Live Runs ({watchedRuns.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {watchedRuns.map((run) => (
                <Badge
                  key={run.runId}
                  variant="primary"
                  className="flex items-center gap-2 cursor-pointer"
                  onClick={() => removeWatchedRun(run.runId)}
                >
                  <RefreshCw className="h-3 w-3 animate-spin" />
                  {run.agentName}
                  <XCircle className="h-3 w-3 hover:text-red-500" />
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Agent Grid */}
      <Tabs defaultValue="standing">
        <TabsList>
          <TabsTrigger value="standing">
            <Clock className="h-4 w-4 mr-2" />
            Standing Agents ({standingAgents.length})
          </TabsTrigger>
          <TabsTrigger value="adhoc">
            <Bot className="h-4 w-4 mr-2" />
            Ad-hoc Agents ({adhocAgents.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="standing" className="mt-4">
          {agentsLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-48 skeleton rounded-xl" />
              ))}
            </div>
          ) : standingAgents.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Clock className="h-12 w-12 text-gray-300 mx-auto" />
                <p className="mt-4 text-gray-900 font-medium">
                  No standing agents
                </p>
                <p className="text-sm text-gray-500">
                  Standing agents run on a schedule automatically
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {standingAgents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onSelect={() => setSelectedAgent(agent)}
                  onRun={() => runMutation.mutate(agent.id)}
                  isRunning={runMutation.isPending}
                />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="adhoc" className="mt-4">
          {agentsLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-48 skeleton rounded-xl" />
              ))}
            </div>
          ) : adhocAgents.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Bot className="h-12 w-12 text-gray-300 mx-auto" />
                <p className="mt-4 text-gray-900 font-medium">No ad-hoc agents</p>
                <p className="text-sm text-gray-500">
                  Spawn an investigator to create an ad-hoc agent
                </p>
                <Button
                  className="mt-4"
                  onClick={() => setIsInvestigatorOpen(true)}
                >
                  <Search className="h-4 w-4 mr-2" />
                  Spawn Investigator
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {adhocAgents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onSelect={() => setSelectedAgent(agent)}
                  onRun={() => runMutation.mutate(agent.id)}
                  isRunning={runMutation.isPending}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Agent Detail Dialog */}
      <Dialog
        open={!!selectedAgent}
        onOpenChange={() => {
          setSelectedAgent(null);
          setSelectedRun(null);
        }}
      >
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          {selectedAgent && (
            <>
              <DialogHeader>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
                      {agentTypeIcons[selectedAgent.type]}
                    </div>
                    <div>
                      <DialogTitle>{selectedAgent.name}</DialogTitle>
                      <p className="text-sm text-gray-500">
                        {agentTypeLabels[selectedAgent.type]}
                      </p>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => runMutation.mutate(selectedAgent.id)}
                    disabled={runMutation.isPending}
                    loading={runMutation.isPending}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Run Now
                  </Button>
                </div>
              </DialogHeader>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-4">
                {/* Runs List */}
                <div className="lg:col-span-1">
                  <h4 className="text-sm font-medium text-gray-900 mb-3">
                    Recent Runs
                  </h4>
                  {runsLoading ? (
                    <div className="space-y-2">
                      {[1, 2, 3].map((i) => (
                        <div key={i} className="h-16 skeleton rounded-lg" />
                      ))}
                    </div>
                  ) : runs?.items.length === 0 ? (
                    <p className="text-sm text-gray-500">No runs yet</p>
                  ) : (
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {runs?.items.map((run) => (
                        <div
                          key={run.id}
                          onClick={() => setSelectedRun(run)}
                          className={cn(
                            "p-3 rounded-lg border cursor-pointer transition-colors",
                            selectedRun?.id === run.id
                              ? "border-lantern-500 bg-lantern-50"
                              : "border-gray-200 hover:border-gray-300"
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <Badge className={getStatusColor(run.status)}>
                              {statusIcons[run.status]}
                              <span className="ml-1 capitalize">
                                {run.status}
                              </span>
                            </Badge>
                            <span className="text-xs text-gray-500">
                              {formatRelativeTime(run.started_at)}
                            </span>
                          </div>
                          {run.cost && (
                            <p className="text-xs text-gray-500 mt-1">
                              {formatCurrency(run.cost.estimated_cost_usd)}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Run Details */}
                <div className="lg:col-span-2">
                  {selectedRun ? (
                    <RunDetails run={selectedRun} />
                  ) : (
                    <div className="flex items-center justify-center h-64 text-gray-500">
                      Select a run to view details
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Spawn Investigator Dialog */}
      <Dialog open={isInvestigatorOpen} onOpenChange={setIsInvestigatorOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Spawn Investigator</DialogTitle>
            <DialogDescription>
              Ask a question and let the AI investigate across your data
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Subject
              </label>
              <Select
                value={investigatorRequest.subject_id}
                onValueChange={(value) =>
                  setInvestigatorRequest({
                    ...investigatorRequest,
                    subject_id: value,
                  })
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
                Question
              </label>
              <textarea
                value={investigatorRequest.question}
                onChange={(e) =>
                  setInvestigatorRequest({
                    ...investigatorRequest,
                    question: e.target.value,
                  })
                }
                placeholder="What do you want to investigate?"
                className="w-full h-24 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-lantern-500 focus:border-transparent resize-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Depth
              </label>
              <Select
                value={investigatorRequest.depth}
                onValueChange={(value) =>
                  setInvestigatorRequest({
                    ...investigatorRequest,
                    depth: value as "shallow" | "medium" | "deep",
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="shallow">
                    Shallow (faster, less thorough)
                  </SelectItem>
                  <SelectItem value="medium">Medium (balanced)</SelectItem>
                  <SelectItem value="deep">
                    Deep (thorough, more expensive)
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsInvestigatorOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={() => investigatorMutation.mutate(investigatorRequest)}
              disabled={
                !investigatorRequest.subject_id ||
                !investigatorRequest.question.trim() ||
                investigatorMutation.isPending
              }
              loading={investigatorMutation.isPending}
            >
              <Search className="h-4 w-4 mr-2" />
              Start Investigation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AgentCard({
  agent,
  onSelect,
  onRun,
  isRunning,
}: {
  agent: Agent;
  onSelect: () => void;
  onRun: () => void;
  isRunning: boolean;
}) {
  return (
    <Card
      className="cursor-pointer hover:shadow-medium transition-shadow"
      onClick={onSelect}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-lantern-100 text-lantern-700">
            {agentTypeIcons[agent.type]}
          </div>
          <Badge className={getStatusColor(agent.status)}>
            {statusIcons[agent.status]}
            <span className="ml-1 capitalize">{agent.status}</span>
          </Badge>
        </div>

        <h3 className="font-medium text-gray-900 mb-1">{agent.name}</h3>
        <p className="text-sm text-gray-500 mb-3">
          {agentTypeLabels[agent.type]}
        </p>

        {agent.schedule && (
          <div className="text-xs text-gray-500 mb-3">
            <Clock className="h-3 w-3 inline mr-1" />
            {agent.schedule.cron}
            {agent.schedule.next_run && (
              <span className="ml-2">
                Next: {formatRelativeTime(agent.schedule.next_run)}
              </span>
            )}
          </div>
        )}

        {agent.last_run?.cost && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <DollarSign className="h-3 w-3" />
            Last run: {formatCurrency(agent.last_run.cost.estimated_cost_usd)}
          </div>
        )}

        <div className="mt-3 pt-3 border-t border-gray-100">
          <Button
            size="sm"
            className="w-full"
            onClick={(e) => {
              e.stopPropagation();
              onRun();
            }}
            disabled={isRunning || agent.status === "running"}
            loading={isRunning}
          >
            <Play className="h-4 w-4 mr-2" />
            Run Now
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RunDetails({ run }: { run: AgentRun }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Badge className={getStatusColor(run.status)}>
          {statusIcons[run.status]}
          <span className="ml-1 capitalize">{run.status}</span>
        </Badge>
        <div className="text-sm text-gray-500">
          {run.duration_ms && (
            <span>{(run.duration_ms / 1000).toFixed(2)}s</span>
          )}
        </div>
      </div>

      {/* Cost */}
      {run.cost && (
        <Card>
          <CardContent className="p-3">
            <div className="grid grid-cols-4 gap-4 text-center text-sm">
              <div>
                <p className="text-gray-500">Input</p>
                <p className="font-medium">{run.cost.input_tokens}</p>
              </div>
              <div>
                <p className="text-gray-500">Output</p>
                <p className="font-medium">{run.cost.output_tokens}</p>
              </div>
              <div>
                <p className="text-gray-500">Total</p>
                <p className="font-medium">{run.cost.total_tokens}</p>
              </div>
              <div>
                <p className="text-gray-500">Cost</p>
                <p className="font-medium text-lantern-600">
                  {formatCurrency(run.cost.estimated_cost_usd)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Error */}
      {run.error && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-3">
            <p className="text-sm text-red-700 font-mono">{run.error}</p>
          </CardContent>
        </Card>
      )}

      {/* Traces */}
      <div>
        <h4 className="text-sm font-medium text-gray-900 mb-2 flex items-center gap-2">
          <Terminal className="h-4 w-4" />
          Traces ({run.traces.length})
        </h4>
        <div className="bg-gray-900 rounded-lg p-4 max-h-64 overflow-y-auto font-mono text-xs">
          {run.traces.length === 0 ? (
            <p className="text-gray-500">No traces available</p>
          ) : (
            <div className="space-y-1">
              {run.traces.map((trace, i) => (
                <TraceEntry key={i} trace={trace} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TraceEntry({ trace }: { trace: AgentTrace }) {
  const levelColors = {
    debug: "text-gray-500",
    info: "text-blue-400",
    warn: "text-amber-400",
    error: "text-red-400",
  };

  return (
    <div className="flex gap-2">
      <span className="text-gray-600 flex-shrink-0">
        {new Date(trace.timestamp).toLocaleTimeString()}
      </span>
      <span className={cn("flex-shrink-0 uppercase", levelColors[trace.level])}>
        [{trace.level}]
      </span>
      <span className="text-gray-300">{trace.message}</span>
    </div>
  );
}
