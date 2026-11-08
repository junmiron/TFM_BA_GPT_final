import { Badge } from '../../../ui/src/components/ui/Badge';

interface DemoHeaderProps {
  lanes: string[];
}

export function DemoHeader({ lanes }: DemoHeaderProps) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-card px-4 py-3 sm:px-6">
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-foreground">BA-GPT</span>
        <Badge tone="info">interactive demo</Badge>
        <span className="text-xs text-muted-foreground">
          scripted replay of a real session &middot; pause &amp; speed control
        </span>
      </div>
      <div className="flex items-center gap-3">
        {lanes.length > 0 && (
          <span className="text-xs text-muted-foreground" aria-hidden="false">
            {lanes.join(' \u00b7 ')}
          </span>
        )}
        <a className="text-xs text-muted-foreground" href="/ba-gpt/">&larr; portfolio</a>
        <a
          className="text-xs text-muted-foreground"
          href="https://github.com/junmiron/TFM_BA_GPT_final"
          target="_blank"
          rel="noopener"
        >
          GitHub &#8600;
        </a>
      </div>
    </header>
  );
}
