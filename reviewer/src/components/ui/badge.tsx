import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center whitespace-nowrap border px-1.5 py-px text-2xs font-semibold uppercase tracking-label leading-4 transition-colors",
  {
    variants: {
      variant: {
        default: "border-ink bg-ink text-white",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-rule-strong text-foreground",
        muted: "border-rule text-muted-foreground",
        destructive: "border-signal bg-signal text-white",
        signal: "border-signal text-signal",
        pass: "border-pass bg-pass text-white",
        passOutline: "border-pass text-pass",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
