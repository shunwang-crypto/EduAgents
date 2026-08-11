import type { ButtonHTMLAttributes, ReactNode } from "react";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  children: ReactNode;
  size?: "sm" | "md";
}

/** 统一图标按钮：36×36、圆角 8、hover/focus-visible、必填 aria-label。 */
export function IconButton({ label, children, size = "md", className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      className={`ea-icon-button ${size === "sm" ? "sm" : ""} ${className ?? ""}`}
      aria-label={label}
      title={rest.title ?? label}
      {...rest}
    >
      {children}
    </button>
  );
}
