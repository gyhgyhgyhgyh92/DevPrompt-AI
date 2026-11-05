import { Navigate, Route, Routes } from 'react-router'
import { HistoryPage } from '../pages/HistoryPage'
import { OptimizePage } from '../pages/OptimizePage'

/** 路由表（F-702 两页：/ 、/history）；未知路径兜底回优化主页。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OptimizePage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
