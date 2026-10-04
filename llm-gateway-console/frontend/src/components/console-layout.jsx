import { Activity, BookOpenText, Braces, Gauge, KeyRound, LogOut, MessageSquare, Network, RefreshCw, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { API_BASE_URL } from '@/lib/api';
import { cn } from '@/lib/utils';

export const consolePages = [
  { name: 'Overview', icon: Gauge, group: 'Operations', description: 'Registered nodes, routing readiness, and recent gateway activity.' },
  { name: 'Nodes', icon: Server, group: 'Operations', description: 'Register gsai computers or other OpenAI-compatible backends.' },
  { name: 'Models', icon: Braces, group: 'Operations', description: 'Manage the model inventory imported from your nodes.' },
  { name: 'Playground', icon: MessageSquare, group: 'Operations', description: 'Choose a model. Write a prompt. Explore the response.' },
  { name: 'Requests', icon: Activity, group: 'Operations', description: 'Inspect individual upstream attempts, durations, and failures.' },
  { name: 'API Keys', icon: KeyRound, group: 'Access', description: 'Control which nodes and models client applications may use.' },
  { name: 'Docs', icon: BookOpenText, group: 'Access', description: 'Set up computers, understand routing, and connect your applications.' },
];

export function ConsoleLayout({ page, onNavigate, onRefresh, onLogout, children }) {
  const current = consolePages.find((item) => item.name === page) || consolePages[0];
  return (
    <div className="min-h-screen bg-background">
      <a href="#console-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:p-3">Skip to content</a>
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r bg-card lg:flex">
        <div className="flex items-center gap-3 border-b px-6 py-6">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Network className="h-5 w-5" /></div>
          <div><strong className="block text-sm">GettingStarted AI</strong><span className="text-xs text-muted-foreground">Router Console</span></div>
        </div>
        <nav aria-label="Main navigation" className="flex-1 space-y-7 px-4 py-6">
          {['Operations', 'Access'].map((group) => (
            <div key={group}>
              <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{group}</p>
              <div className="grid gap-1">
                {consolePages.filter((item) => item.group === group).map(({ name, icon: Icon }) => (
                  <button key={name} type="button" aria-current={page === name ? 'page' : undefined} onClick={() => onNavigate(name)} className={cn('flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent', page === name ? 'bg-primary/10 font-semibold text-primary' : 'text-muted-foreground')}>
                    <Icon className="h-4 w-4" />{name}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="m-4 rounded-xl border bg-muted/30 p-4">
          <p className="text-xs font-semibold">Model-based routing</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Local AI selects from permitted, reachable models. See Models for selector status and fallback settings. Native capacity telemetry is not available.</p>
        </div>
      </aside>
      <div className={cn('lg:pl-64', page === 'Playground' && 'flex h-[100dvh] flex-col overflow-hidden')}>
        <header className="sticky top-0 z-10 shrink-0 border-b bg-card/95 backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 lg:px-8">
            <div className="min-w-0"><p className="text-xs font-medium text-muted-foreground">Router workspace</p><p className="mt-1 break-all font-mono text-xs">{API_BASE_URL}</p></div>
            <div className="flex gap-2"><Button variant="outline" size="sm" onClick={onRefresh}><RefreshCw className="h-4 w-4" />Refresh</Button><Button variant="ghost" size="sm" onClick={onLogout}><LogOut className="h-4 w-4" />Sign out</Button></div>
          </div>
          <nav aria-label="Mobile navigation" className="flex gap-1 overflow-x-auto border-t px-4 py-2 lg:hidden">
            {consolePages.map(({ name }) => <Button key={name} variant={page === name ? 'secondary' : 'ghost'} size="sm" aria-current={page === name ? 'page' : undefined} onClick={() => onNavigate(name)} className="shrink-0">{name}</Button>)}
          </nav>
        </header>
        <main id="console-content" className={cn('mx-auto w-full max-w-[1600px] px-4 lg:px-8', page === 'Playground' ? 'flex min-h-0 flex-1 flex-col py-4 lg:py-5' : 'py-7 lg:py-9')}>
          <div className={cn('shrink-0', page === 'Playground' ? 'mb-4' : 'mb-7')}><h1 className="text-3xl font-semibold tracking-tight">{current.name}</h1><p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">{current.description}</p></div>
          {children}
        </main>
      </div>
    </div>
  );
}
