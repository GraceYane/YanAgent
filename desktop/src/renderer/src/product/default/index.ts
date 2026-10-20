import type { ProductExtension } from '../types'

// Default: no extensions. All behavior stays as-is. An alternate build can
// override the '@product' alias to point at its own module (see
// vite.config.ts) exporting a populated ProductExtension.
export const product: ProductExtension = {
  // The scaffold has no model adapter yet, so the production onboarding flow
  // would be misleading. Re-enable it after Phase 1 is implemented.
  onboarding: { enabled: false },
  nav: { hideExternalLinks: true },
}
