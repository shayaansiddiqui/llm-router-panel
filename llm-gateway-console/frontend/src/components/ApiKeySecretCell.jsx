import { Check, Copy, Eye, EyeOff, Loader2, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function ApiKeySecretCell({ apiKey, isVisible, isCopied, isRegenerating, onToggle, onCopy, onRegenerate }) {
  const canReveal = Boolean(apiKey.key_value);
  const displayValue = canReveal && isVisible ? apiKey.key_value : `${apiKey.key_prefix}...`;

  return (
    <div className="flex max-w-[360px] items-center gap-2">
      <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{displayValue}</code>
      {canReveal && (
        <>
          <Button type="button" variant="ghost" size="icon" onClick={onToggle} aria-label={isVisible ? 'Hide API key' : 'Show API key'}>
            {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </Button>
          <Button type="button" variant="ghost" size="icon" onClick={onCopy} aria-label="Copy API key">
            {isCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </Button>
        </>
      )}
      {!canReveal && (
        <Button type="button" variant="outline" size="sm" onClick={onRegenerate} disabled={isRegenerating}>
          {isRegenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
          Regenerate
        </Button>
      )}
    </div>
  );
}
