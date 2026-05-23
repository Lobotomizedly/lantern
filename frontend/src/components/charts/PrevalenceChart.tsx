"use client";

import React from "react";
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { PrevalencePoint } from "@/types";
import { format, parseISO } from "date-fns";

interface PrevalenceChartProps {
  data: PrevalencePoint[];
  height?: number;
  showPercentage?: boolean;
}

export function PrevalenceChart({
  data,
  height = 250,
  showPercentage = true,
}: PrevalenceChartProps) {
  const formatXAxis = (dateStr: string) => {
    try {
      return format(parseISO(dateStr), "MMM d");
    } catch {
      return dateStr;
    }
  };

  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{ name: string; value: number; color: string }>;
    label?: string;
  }) => {
    if (!active || !payload || !label) return null;

    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3">
        <p className="font-medium text-gray-900 mb-2">
          {format(parseISO(label), "MMM d, yyyy")}
        </p>
        <div className="space-y-1">
          {payload.map((entry) => (
            <div key={entry.name} className="flex items-center gap-2 text-sm">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-gray-600">
                {entry.name === "count" ? "Mentions" : "Share"}:
              </span>
              <span className="font-medium text-gray-900">
                {entry.name === "percentage"
                  ? `${(entry.value * 100).toFixed(1)}%`
                  : entry.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart
        data={data}
        margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
      >
        <defs>
          <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ed7a1b" stopOpacity={0.8} />
            <stop offset="95%" stopColor="#ed7a1b" stopOpacity={0.2} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="date"
          tickFormatter={formatXAxis}
          stroke="#9ca3af"
          fontSize={12}
          tickLine={false}
        />
        <YAxis
          yAxisId="left"
          stroke="#9ca3af"
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        {showPercentage && (
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke="#9ca3af"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `${(value * 100).toFixed(0)}%`}
          />
        )}
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ paddingTop: 20 }}
          formatter={(value) => (
            <span className="text-sm text-gray-600">
              {value === "count" ? "Mentions" : "Share of Voice"}
            </span>
          )}
        />
        <Bar
          yAxisId="left"
          dataKey="count"
          fill="url(#colorCount)"
          radius={[4, 4, 0, 0]}
        />
        {showPercentage && (
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="percentage"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ fill: "#3b82f6", strokeWidth: 2, r: 4 }}
            activeDot={{ r: 6 }}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
