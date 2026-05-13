import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center whitespace-nowrap text-sm font-medium outline-none transition duration-200 focus-visible:ring-2 focus-visible:ring-ink/20 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:
          "bg-graphite text-white shadow-control hover:bg-graphite/90 active:translate-y-px",
        ghost:
          "text-ink hover:bg-ink/5 active:bg-ink/10",
        soft:
          "border border-line/80 bg-panel text-ink shadow-insetPanel hover:bg-bluewash/35",
      },
      size: {
        icon: "h-9 w-9 rounded-full",
        sm: "h-8 rounded-full px-3",
        md: "h-10 rounded-full px-4",
      },
    },
    defaultVariants: {
      variant: "soft",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
