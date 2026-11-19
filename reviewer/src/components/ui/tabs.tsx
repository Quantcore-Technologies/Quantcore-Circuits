import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.List
      ref={ref}
      // equal-width cells, two rows of four below lg; never a scroll container (no overflow, no scrollbar).
      // Selected state is styled from aria-selected: a wrapping TooltipTrigger overrides data-state.
      className={cn("grid w-full grid-cols-4 border-b border-rule text-muted-foreground lg:grid-cols-8", className)}
      {...props}
    />
  ),
);
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "relative flex h-11 min-w-0 items-center gap-2 whitespace-nowrap border-l border-rule px-3 pt-[3px] text-xs font-semibold uppercase tracking-label transition-colors first:border-l-0 first:pl-0 max-lg:[&:nth-child(4n+1)]:border-l-0 max-lg:[&:nth-child(4n+1)]:pl-0",
      "hover:bg-paper hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
      "after:absolute after:inset-x-0 after:-bottom-px after:h-[2px] after:content-[''] aria-selected:text-foreground aria-selected:after:bg-ink",
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content ref={ref} className={cn("mt-6 focus-visible:outline-none", className)} {...props} />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
