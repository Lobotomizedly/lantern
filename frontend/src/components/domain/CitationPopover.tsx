"use client";

import React from "react";
import { ExternalLink, Calendar, Building } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/Popover";
import { Badge } from "@/components/ui/Badge";
import { Citation, Item } from "@/types";
import { formatDateTime, getSentimentBgColor } from "@/lib/utils";

interface CitationPopoverProps {
  citation: Citation;
  children: React.ReactNode;
}

export function CitationPopover({ citation, children }: CitationPopoverProps) {
  const item = citation.item;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <span className="cursor-pointer border-b border-dashed border-lantern-400 text-lantern-700 hover:text-lantern-800 hover:border-lantern-600 transition-colors">
          {children}
        </span>
      </PopoverTrigger>
      <PopoverContent className="w-96" align="start">
        <div className="space-y-3">
          {/* Citation Text */}
          <div>
            <p className="text-xs text-gray-500 mb-1">Cited text</p>
            <p className="text-sm text-gray-900 italic">&ldquo;{citation.text}&rdquo;</p>
          </div>

          {/* Source Item */}
          {item && (
            <div className="pt-3 border-t border-gray-200">
              <p className="text-xs text-gray-500 mb-2">Source</p>
              <div className="space-y-2">
                <h4 className="font-medium text-gray-900 text-sm">
                  {item.title}
                </h4>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span className="flex items-center gap-1">
                    <Building className="h-3 w-3" />
                    {item.source.name}
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {formatDateTime(item.published_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge
                    className={getSentimentBgColor(item.sentiment)}
                    variant="default"
                  >
                    {item.sentiment}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    {item.type.replace("_", " ")}
                  </Badge>
                </div>
                {item.summary && (
                  <p className="text-xs text-gray-600 line-clamp-2">
                    {item.summary}
                  </p>
                )}
                {item.url && (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-lantern-600 hover:text-lantern-700"
                  >
                    View original source
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            </div>
          )}

          {/* Provenance */}
          {item?.provenance && (
            <div className="pt-2 border-t border-gray-100 text-xs text-gray-400">
              <p>
                Retrieved {formatDateTime(item.provenance.retrieved_at)} via{" "}
                {item.provenance.extraction_method}
              </p>
              <p>Confidence: {Math.round(item.provenance.confidence * 100)}%</p>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// Utility component for rendering text with citation markers
interface CitedTextProps {
  text: string;
  citations: Citation[];
}

export function CitedText({ text, citations }: CitedTextProps) {
  // Sort citations by position
  const sortedCitations = [...citations].sort((a, b) => a.position - b.position);

  if (sortedCitations.length === 0) {
    return <span>{text}</span>;
  }

  // Build segments with citations
  const segments: React.ReactNode[] = [];
  let lastIndex = 0;

  sortedCitations.forEach((citation, index) => {
    // Add text before citation
    if (citation.position > lastIndex) {
      segments.push(
        <span key={`text-${index}`}>
          {text.slice(lastIndex, citation.position)}
        </span>
      );
    }

    // Add citation marker
    segments.push(
      <CitationPopover key={`cite-${index}`} citation={citation}>
        <sup className="text-lantern-600 font-medium">[{index + 1}]</sup>
      </CitationPopover>
    );

    lastIndex = citation.position;
  });

  // Add remaining text
  if (lastIndex < text.length) {
    segments.push(<span key="text-final">{text.slice(lastIndex)}</span>);
  }

  return <>{segments}</>;
}
