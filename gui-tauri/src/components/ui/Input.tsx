import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/utils";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "field h-8 rounded-md px-2.5 text-[13px] text-foreground placeholder:text-muted-foreground/60 disabled:pointer-events-none disabled:opacity-45",
          // Callers pass their own width; only default to full width otherwise.
          /(^|\s)(w-|flex-1)/.test(className ?? "") ? null : "w-full",
          className,
        )}
        {...rest}
      />
    );
  },
);
