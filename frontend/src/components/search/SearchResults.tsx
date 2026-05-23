"use client";

import React from "react";
import { Loader2, FileX } from "lucide-react";
import { ItemCard } from "@/components/domain/ItemCard";
import { Button } from "@/components/ui/Button";
import { SearchResult } from "@/types";
import { cn } from "@/lib/utils";

interface SearchResultsProps {
  results: SearchResult | null;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  className?: string;
}

export function SearchResults({
  results,
  isLoading,
  onPageChange,
  className,
}: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className={cn("flex items-center justify-center py-12", className)}>
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-lantern-600 mx-auto" />
          <p className="mt-2 text-sm text-gray-500">Searching...</p>
        </div>
      </div>
    );
  }

  if (!results) {
    return (
      <div className={cn("flex items-center justify-center py-12", className)}>
        <div className="text-center">
          <p className="text-gray-500">Enter a search query to get started</p>
        </div>
      </div>
    );
  }

  if (results.items.length === 0) {
    return (
      <div className={cn("flex items-center justify-center py-12", className)}>
        <div className="text-center">
          <FileX className="h-12 w-12 text-gray-300 mx-auto" />
          <p className="mt-4 text-gray-900 font-medium">No results found</p>
          <p className="mt-1 text-sm text-gray-500">
            Try adjusting your search or filters
          </p>
        </div>
      </div>
    );
  }

  const totalPages = Math.ceil(results.total / results.page_size);

  return (
    <div className={cn("space-y-6", className)}>
      {/* Results Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          Showing{" "}
          <span className="font-medium text-gray-900">
            {(results.page - 1) * results.page_size + 1}
          </span>{" "}
          to{" "}
          <span className="font-medium text-gray-900">
            {Math.min(results.page * results.page_size, results.total)}
          </span>{" "}
          of <span className="font-medium text-gray-900">{results.total}</span>{" "}
          results
        </p>
      </div>

      {/* Results List */}
      <div className="space-y-4">
        {results.items.map((item) => (
          <ItemCard key={item.id} item={item} />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(results.page - 1)}
            disabled={results.page <= 1}
          >
            Previous
          </Button>
          <div className="flex items-center gap-1">
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              let pageNum: number;
              if (totalPages <= 5) {
                pageNum = i + 1;
              } else if (results.page <= 3) {
                pageNum = i + 1;
              } else if (results.page >= totalPages - 2) {
                pageNum = totalPages - 4 + i;
              } else {
                pageNum = results.page - 2 + i;
              }

              return (
                <Button
                  key={pageNum}
                  variant={pageNum === results.page ? "default" : "ghost"}
                  size="sm"
                  onClick={() => onPageChange(pageNum)}
                  className="w-10"
                >
                  {pageNum}
                </Button>
              );
            })}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(results.page + 1)}
            disabled={results.page >= totalPages}
          >
            Next
          </Button>
        </div>
      )}

      {/* Facets Summary */}
      {results.facets && (
        <div className="pt-6 border-t border-gray-200">
          <h4 className="text-sm font-medium text-gray-900 mb-3">
            Results breakdown
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {results.facets.types.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 mb-1">By type</p>
                <div className="space-y-1">
                  {results.facets.types.slice(0, 3).map((facet) => (
                    <div
                      key={facet.value}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-gray-700 capitalize">
                        {facet.value.replace("_", " ")}
                      </span>
                      <span className="text-gray-500">{facet.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {results.facets.sentiments.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 mb-1">By sentiment</p>
                <div className="space-y-1">
                  {results.facets.sentiments.map((facet) => (
                    <div
                      key={facet.value}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-gray-700 capitalize">{facet.value}</span>
                      <span className="text-gray-500">{facet.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {results.facets.sources.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 mb-1">Top sources</p>
                <div className="space-y-1">
                  {results.facets.sources.slice(0, 3).map((facet) => (
                    <div
                      key={facet.value}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-gray-700 truncate">{facet.value}</span>
                      <span className="text-gray-500 flex-shrink-0 ml-2">
                        {facet.count}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
