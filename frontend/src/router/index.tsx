import { Navigate, Route, Routes } from 'react-router'
import { HistoryPage } from '../pages/HistoryPage'
import { OptimizePage } from '../pages/OptimizePage'
import { PreferencePage } from '../pages/PreferencePage'

/** 路由表（F-702 三页：/ 、/history 、/preference）；未知路径兜底回优化主页。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OptimizePage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/preference" element={<PreferencePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
