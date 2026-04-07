import { get } from './client'
import type { DashboardStats } from '../types'

export const fetchDashboardStats = () => get<DashboardStats>('/dashboard/stats')
