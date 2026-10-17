import type { PluginUi } from '../../pluginHost/types';
import { AzureCostPage } from './AzureCostPage';
import { MarketplacePage } from './MarketplacePage';
import { SettingsPage } from './SettingsPage';
import './azure-cost.css';

const ui: PluginUi = {
  routes: [
    { path: '/azure-cost-manager', component: AzureCostPage },
    { path: '/azure-cost-manager/marketplace', component: MarketplacePage },
  ],
  nav: [{ to: '/azure-cost-manager', label: 'Azure Cost', icon: '☁' }],
  settingsPages: [{ path: '', label: 'Azure Cost Manager', component: SettingsPage }],
};

export default ui;
