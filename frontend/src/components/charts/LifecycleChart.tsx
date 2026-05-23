"use client";

import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { LifecyclePoint, LifecycleStage } from "@/types";
import { format, parseISO } from "date-fns";

interface LifecycleChartProps {
  data: LifecyclePoint[];
  height?: number;
  showStageLabels?: boolean;
}

const stageValues: Record<LifecycleStage, number> = {
  dormant: 0,
  emerging: 1,
  growing: 2,
  peak: 3,
  declining: 4,
};

const stageColors: Record<LifecycleStage, string> = {
  emerging: "#3b82f6",
  growing: "#22c55e",
  peak: "#f59e0b",
  declining: "#ef4444",
  dormant: "#6b7280",
};

export function LifecycleChart({
  data,
  height = 200,
  showStageLabels = true,
}: LifecycleChartProps) {
  const chartData = data.map((point) => ({
    ...point,
    stageValue: stageValues[point.stage],
    color: stageColors[point.stage],
  }));

  const formatXAxis = (dateStr: string) => {
    try {
      return format(parseISO(dateStr), "MMM d");
    } catch {
      return dateStr;
    }
  };

  const formatYAxis = (value: number) => {
    const stages: LifecycleStage[] = [
      "dormant",
      "emerging",
      "growing",
      "peak",
      "declining",
    ];
    return stages[value] || "";
  };

  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{
      payload: { stage: LifecycleStage; velocity: number };
    }>;
    label?: string;
  }) => {
    if (!active || !payload || !payload[0] || !label) return null;

    const point = payload[0].payload;

    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3">
        <p className="font-medium text-gray-900 mb-2">
          {format(parseISO(label), "MMM d, yyyy")}
        </p>
        <div className="space-y-1 text-sm">
          <div className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: stageColors[point.stage] }}
            />
            <span className="text-gray-600">Stage:</span>
            <span className="font-medium text-gray-900 capitalize">
              {point.stage}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-600">Velocity:</span>
            <span className="font-medium text-gray-900">
              {point.velocity.toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    );
  };

  const CustomDot = (props: {
    cx?: number;
    cy?: number;
    payload?: { stage: LifecycleStage };
  }) => {
    const { cx, cy, payload } = props;
    if (!cx || !cy || !payload) return null;

    return (
      <circle
        cx={cx}
        cy={cy}
        r={4}
        fill={stageColors[payload.stage]}
        stroke="white"
        strokeWidth={2}
      />
    );
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart
        data={chartData}
        margin={{ top: 10, right: 10, left: showStageLabels ? 80 : 0, bottom: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="date"
          tickFormatter={formatXAxis}
          stroke="#9ca3af"
          fontSize={12}
          tickLine={false}
        />
        <YAxis
          domain={[0, 4]}
          ticks={[0, 1, 2, 3, 4]}
          tickFormatter={showStageLabels ? formatYAxis : undefined}
          stroke="#9ca3af"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          width={showStageLabels ? 70 : 30}
        />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine
          y={3}
          stroke="#f59e0b"
          strokeDasharray="3 3"
          strokeOpacity={0.5}
        />
        <Line
          type="stepAfter"
          dataKey="stageValue"
          stroke="#6b7280"
          strokeWidth={2}
          dot={<CustomDot />}
          activeDot={{ r: 6 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
