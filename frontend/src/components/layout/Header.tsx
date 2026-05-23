"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  Search,
  Menu,
  User,
  Settings,
  LogOut,
  HelpCircle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/Popover";
import { useUIStore } from "@/lib/store";
import { cn } from "@/lib/utils";

interface HeaderProps {
  className?: string;
}

export function Header({ className }: HeaderProps) {
  const pathname = usePathname();
  const { toggleSidebar, sidebarCollapsed } = useUIStore();

  const getPageTitle = () => {
    if (pathname === "/") return "Dashboard";
    if (pathname.startsWith("/subjects")) return "Subjects";
    if (pathname.startsWith("/narratives")) return "Narratives";
    if (pathname.startsWith("/search")) return "Search";
    if (pathname.startsWith("/timeline")) return "Timeline";
    if (pathname.startsWith("/artifacts")) return "Artifacts";
    if (pathname.startsWith("/agents")) return "Agents";
    if (pathname.startsWith("/reviews")) return "Reviews";
    return "Lantern";
  };

  return (
    <header
      className={cn(
        "sticky top-0 z-40 flex h-16 items-center justify-between border-b border-gray-200 bg-white px-4 lg:px-6",
        className
      )}
    >
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="lg:hidden"
        >
          <Menu className="h-5 w-5" />
        </Button>

        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-900">
            {getPageTitle()}
          </h1>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Global Search */}
        <div className="hidden md:block">
          <Link href="/search">
            <div className="relative">
              <Input
                placeholder="Search..."
                className="w-64 lg:w-80 cursor-pointer"
                icon={<Search className="h-4 w-4" />}
                readOnly
              />
            </div>
          </Link>
        </div>

        {/* Mobile Search Button */}
        <Link href="/search" className="md:hidden">
          <Button variant="ghost" size="icon">
            <Search className="h-5 w-5" />
          </Button>
        </Link>

        {/* Notifications */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon" className="relative">
              <Bell className="h-5 w-5" />
              <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-lantern-600 text-2xs text-white">
                3
              </span>
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-80">
            <div className="space-y-4">
              <h3 className="font-semibold text-gray-900">Notifications</h3>
              <div className="space-y-3">
                <NotificationItem
                  title="New narrative detected"
                  description="A new narrative about 'Market Expansion' has emerged"
                  time="2 minutes ago"
                />
                <NotificationItem
                  title="Digest ready"
                  description="Your daily digest for Acme Corp is ready to review"
                  time="1 hour ago"
                />
                <NotificationItem
                  title="Review required"
                  description="3 items pending your review"
                  time="3 hours ago"
                />
              </div>
              <Link
                href="/notifications"
                className="block text-center text-sm text-lantern-600 hover:text-lantern-700"
              >
                View all notifications
              </Link>
            </div>
          </PopoverContent>
        </Popover>

        {/* Help */}
        <Button variant="ghost" size="icon">
          <HelpCircle className="h-5 w-5" />
        </Button>

        {/* User Menu */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon" className="ml-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-lantern-100 text-lantern-700">
                <User className="h-4 w-4" />
              </div>
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-56">
            <div className="space-y-4">
              <div className="border-b border-gray-200 pb-3">
                <p className="font-medium text-gray-900">John Doe</p>
                <p className="text-sm text-gray-500">john@example.com</p>
              </div>
              <nav className="space-y-1">
                <Link
                  href="/settings"
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
                >
                  <Settings className="h-4 w-4" />
                  Settings
                </Link>
                <button className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-gray-700 hover:bg-gray-100">
                  <LogOut className="h-4 w-4" />
                  Sign out
                </button>
              </nav>
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </header>
  );
}

function NotificationItem({
  title,
  description,
  time,
}: {
  title: string;
  description: string;
  time: string;
}) {
  return (
    <div className="flex gap-3 rounded-lg p-2 hover:bg-gray-50 cursor-pointer">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900">{title}</p>
        <p className="text-xs text-gray-500 truncate">{description}</p>
        <p className="text-xs text-gray-400 mt-0.5">{time}</p>
      </div>
    </div>
  );
}
