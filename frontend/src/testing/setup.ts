// Vitest 全局 setup：i18n 必须在组件测试前初始化（同步资源、固定 zh-CN），
// 使既有中文断言与 useTranslation 渲染无需 mock 即可工作。
import '../i18n'
