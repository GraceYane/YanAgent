import type { ProductExtension } from '../types'

// 默认不启用扩展，所有行为保持原样。其他构建版本可以覆盖 '@product'
// 别名，使其指向自定义模块（参见 vite.config.ts），并导出包含具体配置的
// ProductExtension。
export const product: ProductExtension = {
  // 当前脚手架尚未实现模型适配器，显示正式版的新手引导容易产生误导。
  // 完成第一阶段的模型适配后再重新启用。
  onboarding: { enabled: false },
  nav: { hideExternalLinks: true },
}
