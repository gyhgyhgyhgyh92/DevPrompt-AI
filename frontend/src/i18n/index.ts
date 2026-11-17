import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { useSettingsStore } from '../stores/useSettingsStore'
import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'

export { i18n }

export type Locale = 'zh-CN' | 'en'
export const DEFAULT_LOCALE: Locale = 'zh-CN'

/**
 * i18n 初始化（2026-11-06 多语言）：资源同步 import，无异步加载、无网络请求——
 * 测试无需 await 也无需 mock；初始语言取 useSettingsStore 的 appearance.locale
 * （Zod 校验后的唯一真源，localStorage devprompt:v1:appearance）。
 */
void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    en: { translation: en },
  },
  lng: readStoredLocale(),
  fallbackLng: DEFAULT_LOCALE,
  interpolation: { escapeValue: false },
  returnNull: false,
})

function readStoredLocale(): Locale {
  const locale = useSettingsStore.getState().appearance.locale
  return locale === 'en' ? 'en' : DEFAULT_LOCALE
}

/** locale 变更即时生效（App 顶层 effect 调用；appearance.locale 是唯一真源）。 */
export function applyLocale(locale: string): void {
  if (locale === 'en' || locale === 'zh-CN') void i18n.changeLanguage(locale)
}
