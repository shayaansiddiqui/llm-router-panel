import { useMemo } from 'react';
import { Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';

function toIdList(values) {
  return values.map(String);
}

function unique(values) {
  return Array.from(new Set(values));
}

function onRowKeyDown(event, callback) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    callback();
  }
}

export function ApiKeyAccessScope({ providers, models, providerIds, modelIds, onChange }) {
  const modelsByProvider = useMemo(() => {
    return models.reduce((grouped, model) => {
      const key = String(model.provider_id || '');
      grouped[key] = grouped[key] || [];
      grouped[key].push(model);
      return grouped;
    }, {});
  }, [models]);

  const selectedProviderIds = toIdList(providerIds);
  const selectedModelIds = toIdList(modelIds);
  const isAllAccess = selectedProviderIds.length === 0 && selectedModelIds.length === 0;

  function providerModels(providerId) {
    return modelsByProvider[String(providerId)] || [];
  }

  function providerModelIds(providerId) {
    return providerModels(providerId).map((model) => String(model.id));
  }

  function setScope(nextProviderIds, nextModelIds) {
    onChange({
      provider_ids: unique(nextProviderIds),
      model_ids: unique(nextModelIds),
    });
  }

  function allowAll() {
    setScope([], []);
  }

  function allowProvider(providerId) {
    const id = String(providerId);
    setScope(
      selectedProviderIds.includes(id) ? selectedProviderIds : [...selectedProviderIds, id],
      selectedModelIds.filter((modelId) => !providerModelIds(id).includes(modelId))
    );
  }

  function clearProvider(providerId) {
    const id = String(providerId);
    setScope(
      selectedProviderIds.filter((selectedId) => selectedId !== id),
      selectedModelIds.filter((modelId) => !providerModelIds(id).includes(modelId))
    );
  }

  function toggleProvider(providerId) {
    const id = String(providerId);
    const isProviderSelected = selectedProviderIds.includes(id);
    const hasSelectedModels = providerModelIds(id).some((modelId) => selectedModelIds.includes(modelId));

    if (isProviderSelected || hasSelectedModels) {
      clearProvider(id);
      return;
    }

    allowProvider(id);
  }

  function toggleModel(model) {
    const modelId = String(model.id);
    const providerId = String(model.provider_id || '');
    const allModelIds = providerModelIds(providerId);
    const providerIsAllModels = selectedProviderIds.includes(providerId);
    const existingCustomIds = selectedModelIds.filter((id) => !allModelIds.includes(id));
    const providerCustomIds = providerIsAllModels
      ? allModelIds
      : selectedModelIds.filter((id) => allModelIds.includes(id));
    const nextProviderCustomIds = providerCustomIds.includes(modelId)
      ? providerCustomIds.filter((id) => id !== modelId)
      : [...providerCustomIds, modelId];

    const shouldUseProviderAll = allModelIds.length > 0 && nextProviderCustomIds.length === allModelIds.length;
    const nextProviderIds = selectedProviderIds.filter((id) => id !== providerId);

    if (shouldUseProviderAll) {
      setScope([...nextProviderIds, providerId], existingCustomIds);
      return;
    }

    setScope(nextProviderIds, [...existingCustomIds, ...nextProviderCustomIds]);
  }

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold">Access</span>
        {!isAllAccess && (
          <Button type="button" variant="ghost" size="sm" onClick={allowAll}>
            All access
          </Button>
        )}
      </div>

      <div
        role="button"
        tabIndex={0}
        className={cn(
          'flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors hover:bg-muted/50',
          isAllAccess && 'border-primary bg-accent/60'
        )}
        onClick={allowAll}
        onKeyDown={(event) => onRowKeyDown(event, allowAll)}
      >
        <Checkbox checked={isAllAccess} onCheckedChange={allowAll} onClick={(event) => event.stopPropagation()} />
        <span className="text-sm font-medium">All access</span>
      </div>

      <div className="overflow-hidden rounded-md border">
        {providers.map((provider) => {
          const providerId = String(provider.id);
          const modelsForProvider = providerModels(providerId);
          const modelIdsForProvider = providerModelIds(providerId);
          const providerIsAllModels = selectedProviderIds.includes(providerId);
          const selectedModelsForProvider = modelIdsForProvider.filter((id) => selectedModelIds.includes(id));
          const providerIsActive = providerIsAllModels || selectedModelsForProvider.length > 0;
          const selectedCount = providerIsAllModels ? modelIdsForProvider.length : selectedModelsForProvider.length;

          return (
            <div key={provider.id} className="border-b last:border-b-0">
              <div className={cn('flex items-center justify-between gap-3 px-3 py-3', providerIsActive && 'bg-muted/30')}>
                <div
                  role="button"
                  tabIndex={0}
                  className="flex min-w-0 cursor-pointer items-center gap-3 text-left"
                  onClick={() => toggleProvider(provider.id)}
                  onKeyDown={(event) => onRowKeyDown(event, () => toggleProvider(provider.id))}
                >
                  <Checkbox
                    checked={providerIsActive}
                    onCheckedChange={() => toggleProvider(provider.id)}
                    onClick={(event) => event.stopPropagation()}
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{provider.name}</span>
                    {providerIsActive && (
                      <span className="block truncate text-xs text-muted-foreground">
                        {providerIsAllModels ? 'All models' : `${selectedCount} selected`}
                      </span>
                    )}
                  </span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0"
                  onClick={() => (providerIsActive ? clearProvider(provider.id) : allowProvider(provider.id))}
                >
                  {providerIsActive ? 'Clear' : 'All models'}
                </Button>
              </div>

              {providerIsActive && (
                <div className="grid gap-1 border-t bg-background px-3 py-2">
                  {modelsForProvider.length ? (
                    modelsForProvider.map((model) => {
                      const modelId = String(model.id);
                      const checked = providerIsAllModels || selectedModelIds.includes(modelId);

                      return (
                        <div
                          key={model.id}
                          role="button"
                          tabIndex={0}
                          className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-muted/50"
                          onClick={() => toggleModel(model)}
                          onKeyDown={(event) => onRowKeyDown(event, () => toggleModel(model))}
                        >
                          <Checkbox checked={checked} onCheckedChange={() => toggleModel(model)} onClick={(event) => event.stopPropagation()} />
                          <span className="min-w-0 flex-1 truncate text-sm">{model.display_name || model.name}</span>
                          {checked && <Check className="h-4 w-4 shrink-0 text-muted-foreground" />}
                        </div>
                      );
                    })
                  ) : (
                    <div className="px-3 py-2 text-sm text-muted-foreground">No models</div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {!providers.length && <div className="px-3 py-4 text-sm text-muted-foreground">Add a provider first.</div>}
      </div>
    </div>
  );
}
