/**
 * Zod 与生成类型一致性校验（架构文档 §8.8 / F-705 三条防线之三）。
 *
 * 校验内容：
 * 1. 仓库根 openapi.json 可解析，且含 paths 与 components.schemas
 * 2. 生成产物 openapi.generated.ts 覆盖全部契约 schema 名与端点路径
 * 3. 手写 Zod 模块（common/optimize/history/settings/stream）存在且导出运行时校验 schema
 *
 * 退出码：0 = 通过；1 = 契约漂移或缺件。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..', '..')
const openapiPath = path.join(repoRoot, 'openapi.json')
const generatedPath = path.join(here, '..', 'src', 'schemas', 'openapi.generated.ts')
const zodModules = ['common.ts', 'optimize.ts', 'history.ts', 'settings.ts', 'stream.ts']

const errors = []

function check(condition, message) {
  if (!condition) {
    errors.push(message)
  }
}

const openapi = JSON.parse(readFileSync(openapiPath, 'utf8'))
const generated = readFileSync(generatedPath, 'utf8')

const schemaNames = Object.keys(openapi.components?.schemas ?? {})
const paths = Object.keys(openapi.paths ?? {})

check(schemaNames.length > 0, 'openapi.json 无 components.schemas')
check(paths.length > 0, 'openapi.json 无 paths')

for (const name of schemaNames) {
  check(generated.includes(`"${name}"`), `生成类型缺少契约 schema：${name}`)
}

for (const p of paths) {
  check(generated.includes(`"${p}"`), `生成类型缺少端点路径：${p}`)
}

for (const moduleName of zodModules) {
  const source = readFileSync(path.join(here, '..', 'src', 'schemas', moduleName), 'utf8')
  check(/export const \w+Schema\s*=\s*\w+/.test(source), `schemas/${moduleName} 未导出 Zod schema`)
}

if (errors.length > 0) {
  console.error('契约一致性校验未通过：')
  for (const message of errors) {
    console.error(`  - ${message}`)
  }
  process.exit(1)
}

console.log(`契约一致性校验通过：${schemaNames.length} 个 schema，${paths.length} 个端点。`)
