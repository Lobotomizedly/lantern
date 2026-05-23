"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, Sparkles, Clock, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { SearchFilters } from "@/components/search/SearchFilters";
import { SearchResults } from "@/components/search/SearchResults";
import { search, getSources, searchSuggestions } from "@/lib/api";
import { useSearchStore } from "@/lib/store";
import { debounce, cn } from "@/lib/utils";
import { SearchQuery, Source } from "@/types";

export default function SearchPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { query, setQuery, resetQuery, recentSearches, addRecentSearch } =
    useSearchStore();

  const [inputValue, setInputValue] = useState(query.q || "");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showFilters, setShowFilters] = useState(true);

  // Initialize from URL params
  useEffect(() => {
    const q = searchParams.get("q");
    const subjectId = searchParams.get("subject_id");
    if (q || subjectId) {
      setQuery({
        q: q || "",
        subject_id: subjectId || undefined,
      });
      setInputValue(q || "");
    }
  }, [searchParams, setQuery]);

  const { data: sources } = useQuery({
    queryKey: ["sources"],
    queryFn: () => getSources(1, 100),
  });

  const {
    data: results,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["search", query],
    queryFn: () => search(query),
    enabled: !!query.q || !!query.subject_id,
  });

  const fetchSuggestions = useCallback(
    debounce(async (value: string) => {
      if (value.length < 2) {
        setSuggestions([]);
        return;
      }
      try {
        const suggestions = await searchSuggestions(value);
        setSuggestions(suggestions);
      } catch {
        setSuggestions([]);
      }
    }, 300),
    []
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInputValue(value);
    fetchSuggestions(value);
    setShowSuggestions(true);
  };

  const handleSearch = (searchValue?: string) => {
    const q = searchValue ?? inputValue;
    if (q.trim()) {
      addRecentSearch(q.trim());
    }
    setQuery({ q: q.trim(), page: 1 });
    setShowSuggestions(false);
    refetch();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch();
    }
    if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setInputValue(suggestion);
    handleSearch(suggestion);
  };

  const handleRecentSearchClick = (search: string) => {
    setInputValue(search);
    handleSearch(search);
  };

  const handleFilterChange = (updates: Partial<SearchQuery>) => {
    setQuery({ ...updates, page: 1 });
  };

  const handlePageChange = (page: number) => {
    setQuery({ page });
    refetch();
  };

  const handleReset = () => {
    resetQuery();
    setInputValue("");
  };

  const exampleQueries = [
    "What are the latest developments regarding AI regulation?",
    "Show me negative sentiment about product launches",
    "Find articles mentioning executive changes",
    "Recent financial news with high significance",
  ];

  return (
    <div className="space-y-6">
      {/* Search Header */}
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-semibold text-gray-900">
            Search Content
          </h1>
          <p className="text-gray-500 mt-2">
            Use natural language to search across all your items, narratives,
            and events
          </p>
        </div>

        {/* Search Input */}
        <div className="relative">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Input
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                onFocus={() => setShowSuggestions(true)}
                placeholder="Search using natural language..."
                className="h-12 text-lg pl-12"
                icon={<Search className="h-5 w-5" />}
              />
              {inputValue && (
                <button
                  onClick={() => {
                    setInputValue("");
                    setSuggestions([]);
                  }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              )}
            </div>
            <Button onClick={() => handleSearch()} size="lg" className="px-8">
              <Search className="h-5 w-5 mr-2" />
              Search
            </Button>
          </div>

          {/* Suggestions Dropdown */}
          {showSuggestions && (suggestions.length > 0 || recentSearches.length > 0) && (
            <Card className="absolute z-10 w-full mt-2 shadow-lg">
              <CardContent className="p-2">
                {suggestions.length > 0 && (
                  <div className="mb-2">
                    <p className="text-xs text-gray-500 px-2 py-1">Suggestions</p>
                    {suggestions.map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="w-full text-left px-3 py-2 rounded-md hover:bg-gray-100 text-sm flex items-center gap-2"
                      >
                        <Sparkles className="h-4 w-4 text-lantern-500" />
                        {suggestion}
                      </button>
                    ))}
                  </div>
                )}
                {recentSearches.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 px-2 py-1">Recent</p>
                    {recentSearches.slice(0, 5).map((search, i) => (
                      <button
                        key={i}
                        onClick={() => handleRecentSearchClick(search)}
                        className="w-full text-left px-3 py-2 rounded-md hover:bg-gray-100 text-sm flex items-center gap-2"
                      >
                        <Clock className="h-4 w-4 text-gray-400" />
                        {search}
                      </button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Example Queries */}
        {!query.q && !results && (
          <div className="mt-6">
            <p className="text-sm text-gray-500 mb-3">Try searching for:</p>
            <div className="flex flex-wrap gap-2">
              {exampleQueries.map((example, i) => (
                <Badge
                  key={i}
                  variant="outline"
                  className="cursor-pointer hover:bg-gray-100 transition-colors"
                  onClick={() => {
                    setInputValue(example);
                    handleSearch(example);
                  }}
                >
                  {example}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Results Section */}
      {(query.q || query.subject_id || results) && (
        <div className="flex gap-6">
          {/* Filters Sidebar */}
          <div
            className={cn(
              "w-64 flex-shrink-0 transition-all",
              showFilters ? "block" : "hidden lg:block"
            )}
          >
            <div className="sticky top-20">
              <Card>
                <CardContent className="p-4">
                  <SearchFilters
                    query={query}
                    sources={sources?.items ?? []}
                    onQueryChange={handleFilterChange}
                    onReset={handleReset}
                  />
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Results */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-4 lg:hidden">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowFilters(!showFilters)}
              >
                {showFilters ? "Hide Filters" : "Show Filters"}
              </Button>
            </div>
            <SearchResults
              results={results ?? null}
              isLoading={isLoading}
              onPageChange={handlePageChange}
            />
          </div>
        </div>
      )}
    </div>
  );
}
