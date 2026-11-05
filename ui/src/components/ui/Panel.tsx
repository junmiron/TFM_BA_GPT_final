import type { ReactNode } from 'react';
import { cn } from '../../lib/cn';

interface PanelProps {
  title?: string;
  /** Id of the heading element, so the panel can be labelled by it. */
  headingId?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
  as?: 'section' | 'aside' | 'div';
}

/** Card with the prototype's rounded, shadowed white surface. */
export function Panel({ title, headingId, action, className, children, as: Tag = 'section' }: PanelProps) {
  return (
    <Tag
      aria-labelledby={title && headingId ? headingId : undefined}
      className={cn('flex min-h-0 flex-col rounded-lg border border-border bg-card shadow-lg', className)}
    >
      {title && (
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 id={headingId} className="text-sm font-semibold text-foreground">
            {title}
          </h2>
          {action}
        </div>
      )}
      {children}
    </Tag>
  );
}
