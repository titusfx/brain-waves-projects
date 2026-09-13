import type { Routes } from '@angular/router';

/**
 * The five screens, in the order an operator actually uses them.
 *
 * Monitor is the landing page because watching the signal is what you do first and
 * most: it is the only screen that answers "is this electrode on properly?".
 */
export const routes: Routes = [
  {
    path: '',
    title: 'Monitor · EPOC+ workbench',
    loadComponent: () => import('./features/monitor/monitor-page').then((m) => m.MonitorPage),
  },
  {
    path: 'channels',
    title: 'Channels · EPOC+ workbench',
    loadComponent: () => import('./features/channels/channels-page').then((m) => m.ChannelsPage),
  },
  {
    path: 'flows',
    title: 'Protocols · EPOC+ workbench',
    loadComponent: () => import('./features/flows/flows-page').then((m) => m.FlowsPage),
  },
  {
    path: 'flows/new',
    title: 'New protocol · EPOC+ workbench',
    loadComponent: () => import('./features/flows/flows-page').then((m) => m.FlowsPage),
    data: { fresh: true },
  },
  {
    path: 'run',
    title: 'Run · EPOC+ workbench',
    loadComponent: () => import('./features/run/run-page').then((m) => m.RunPage),
  },
  {
    path: 'datasets',
    title: 'Datasets · EPOC+ workbench',
    loadComponent: () => import('./features/datasets/datasets-page').then((m) => m.DatasetsPage),
    data: { tab: 'overview' },
  },
  {
    path: 'datasets/:id',
    title: 'Dataset · EPOC+ workbench',
    loadComponent: () => import('./features/datasets/datasets-page').then((m) => m.DatasetsPage),
    data: { tab: 'overview' },
  },
  {
    // Its own route rather than a panel flag: the Discovery view is the one worth
    // linking someone to, and a URL that says so is how that happens.
    path: 'datasets/:id/discovery',
    title: 'Discovery · EPOC+ workbench',
    loadComponent: () => import('./features/datasets/datasets-page').then((m) => m.DatasetsPage),
    data: { tab: 'discovery' },
  },
  { path: '**', redirectTo: '' },
];
