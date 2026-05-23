"use client";

import React from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { SentimentChartData } from "@/types";
import { format, parseISO } from "date-fns";

interface SentimentChartProps {
  data: SentimentChartData[];
  height?: number;
  showLegend?: boolean;
}

export function SentimentChart({
  data,
  height = 300,
  showLegend = true,
}: SentimentChartProps) {
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
              <span className="text-gray-600 capitalize">{entry.name}:</span>
              <span className="font-medium text-gray-900">{entry.value}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={data}
        margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
      >
        <defs>
          <linearGradient id="colorPositive" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorNeutral" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#6b7280" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#6b7280" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorNegative" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorMixed" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
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
          stroke="#9ca3af"
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip content={<CustomTooltip />} />
        {showLegend && (
          <Legend
            wrapperStyle={{ paddingTop: 20 }}
            formatter={(value) => (
              <span className="text-sm text-gray-600 capitalize">{value}</span>
            )}
          />
        )}
        <Area
          type="monotone"
          dataKey="positive"
          stackId="1"
          stroke="#22c55e"
          fill="url(#colorPositive)"
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="neutral"
          stackId="1"
          stroke="#6b7280"
          fill="url(#colorNeutral)"
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="mixed"
          stackId="1"
          stroke="#f59e0b"
          fill="url(#colorMixed)"
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="negative"
          stackId="1"
          stroke="#ef4444"
          fill="url(#colorNegative)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
