import { get, post } from './client'
import type { Skill, SkillCreate } from '../types'

export const fetchSkills    = () => get<{ skills: Skill[]; total: number }>('/skills')
export const installSkill   = (data: SkillCreate) => post<{ skill_id: string; file_path: string; assigned_to: string[] }>('/skills/install', data)
