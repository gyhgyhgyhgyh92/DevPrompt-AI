/** 样张页的类型面：只描述「试哪几套视觉 / 演示什么」，不含任何业务判定。 */

export type LabStyleId = 'blueprint' | 'terminal' | 'soft'
export type LabPaletteId = 'signal' | 'graphite' | 'amber'
export type LabStreamVariant = 'typewriter' | 'rail' | 'digest'
export type LabThemeMode = 'light' | 'dark' | 'system'
export type LabStartComposition = 'centered' | 'split'

export const LAB_STYLES: readonly LabStyleId[] = ['blueprint', 'terminal', 'soft']
export const LAB_PALETTES: readonly LabPaletteId[] = ['signal', 'graphite', 'amber']
export const LAB_VARIANTS: readonly LabStreamVariant[] = ['typewriter', 'rail', 'digest']
export const LAB_THEMES: readonly LabThemeMode[] = ['light', 'dark', 'system']
export const LAB_COMPOSITIONS: readonly LabStartComposition[] = ['centered', 'split']

/** 工具动作的三种展示形态（数据同一份，只是信息密度与排布不同）。 */
export type LabToolForm = 'pill' | 'card' | 'terminal'
