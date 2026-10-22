import type { PluginUi } from '../../pluginHost/types';
import { AzureCostPage } from './AzureCostPage';
import { FinOpsPage } from './FinOpsPage';
import { GrowthPage } from './GrowthPage';
import { WhitespacePage } from './WhitespacePage';
import { MarketplaceWhitespacePage } from './MarketplaceWhitespacePage';
import { HygienePage } from './HygienePage';
import { RenewalsPage } from './RenewalsPage';
import { QuotaPage } from './Quota';
import { MarketplacePage } from './MarketplacePage';
import { ReportsHome } from './ReportsHome';
import { SettingsPage } from './SettingsPage';
import { TagCoveragePage } from './TagCoveragePage';
import './azure-cost.css';

const ui: PluginUi = {
  routes: [
    { path: '/azure-cost-manager', component: ReportsHome },
    { path: '/azure-cost-manager/report', component: AzureCostPage },
    { path: '/azure-cost-manager/marketplace', component: MarketplacePage },
    { path: '/azure-cost-manager/finops', component: FinOpsPage },
    { path: '/azure-cost-manager/tags', component: TagCoveragePage },
    { path: '/azure-cost-manager/growth', component: GrowthPage },
    { path: '/azure-cost-manager/whitespace', component: WhitespacePage },
    { path: '/azure-cost-manager/marketplace-whitespace', component: MarketplaceWhitespacePage },
    { path: '/azure-cost-manager/hygiene', component: HygienePage },
    { path: '/azure-cost-manager/renewals', component: RenewalsPage },
    { path: '/azure-cost-manager/quota', component: QuotaPage },
  ],
  nav: [{ to: '/azure-cost-manager', label: 'Azure Cost', icon: '☁' }],
  settingsPages: [{ path: '', label: 'Azure Cost Manager', component: SettingsPage }],
};

export default ui;
